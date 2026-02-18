"""PostgreSQL database operations."""

import json
import logging
from contextlib import contextmanager
from typing import Optional
from urllib.parse import urlparse

import psycopg2
import psycopg2.extensions
from psycopg2.pool import SimpleConnectionPool
from psycopg2 import sql

from .config import config

logger = logging.getLogger(__name__)

# Connection pool configuration
POOL_MIN_CONNECTIONS = 1
POOL_MAX_CONNECTIONS = 5

# Database configuration
DEFAULT_POSTGRES_DATABASE = "postgres"
DEFAULT_SCHEMA = "public"
TABLE_NAME = "consumption_messages"

# Connection pool (initialized on first use)
_pool: Optional[SimpleConnectionPool] = None


def parse_database_url(url: str) -> dict:
    """Parse PostgreSQL connection URL into components."""
    parsed = urlparse(url)
    return {
        "user": parsed.username,
        "password": parsed.password,
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "database": parsed.path.lstrip("/") if parsed.path else None,
    }


def _validate_database_name(name: str) -> None:
    """Validate database name contains only safe characters."""
    safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if not all(c in safe_chars for c in name):
        raise ValueError(f"Invalid database name (contains unsafe characters): {name}")


def create_database_if_not_exists() -> None:
    """Create database if it doesn't exist (best-effort, may fail if insufficient permissions)."""
    db_config = parse_database_url(config.DATABASE_URL)
    database_name = db_config["database"]

    if not database_name:
        raise ValueError("Database name not found in DATABASE_URL")

    _validate_database_name(database_name)

    # Connect to default 'postgres' database to create target database
    admin_url = (
        f"postgresql://{db_config['user']}:{db_config['password']}"
        f"@{db_config['host']}:{db_config['port']}/{DEFAULT_POSTGRES_DATABASE}"
    )

    logger.info(f"Checking if database '{database_name}' exists")

    try:
        conn = psycopg2.connect(admin_url)
        conn.autocommit = True  # Required for CREATE DATABASE
        cur = conn.cursor()

        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database_name,))
        exists = cur.fetchone() is not None

        if not exists:
            logger.info(f"Creating database '{database_name}'")
            # CREATE DATABASE doesn't support parameters, but name is validated
            cur.execute(f'CREATE DATABASE "{database_name}"')
            logger.info(f"Database '{database_name}' created successfully")
        else:
            logger.debug(f"Database '{database_name}' already exists")

        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to create database: {e}")
        raise


def create_schema_if_not_exists(schema_name: str = DEFAULT_SCHEMA) -> None:
    """Create schema if it doesn't exist (best-effort)."""
    logger.info(f"Checking if schema '{schema_name}' exists")

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
                    (schema_name,),
                )
                exists = cur.fetchone() is not None

                if not exists:
                    logger.info(f"Creating schema '{schema_name}'")
                    cur.execute(
                        sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                            sql.Identifier(schema_name)
                        )
                    )
                    logger.info(f"Schema '{schema_name}' created successfully")
                else:
                    logger.debug(f"Schema '{schema_name}' already exists")
    except Exception as e:
        logger.error(f"Failed to create schema: {e}")
        raise


def get_pool() -> SimpleConnectionPool:
    """Get or create database connection pool."""
    global _pool
    if _pool is None:
        logger.info("Creating database connection pool")
        _pool = SimpleConnectionPool(
            minconn=POOL_MIN_CONNECTIONS,
            maxconn=POOL_MAX_CONNECTIONS,
            dsn=config.DATABASE_URL,
        )
        if _pool is None:
            raise RuntimeError("Failed to create database connection pool")
    return _pool


@contextmanager
def get_connection():
    """Get a database connection from the pool."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _get_table_identifier(schema_name: str) -> sql.Identifier:
    """Create schema-qualified table identifier."""
    return sql.Identifier(schema_name, TABLE_NAME)


def _create_table_and_indexes(schema_name: str) -> None:
    """Create consumption_messages table and indexes if they don't exist."""
    table_name = _get_table_identifier(schema_name)
    idx_hash_name = sql.Identifier("idx_content_hash")
    idx_date_name = sql.Identifier("idx_message_date")

    create_table_sql = sql.SQL("""
    CREATE TABLE IF NOT EXISTS {table} (
        id SERIAL PRIMARY KEY,
        content_hash VARCHAR(64) UNIQUE NOT NULL,
        message_date DATE NOT NULL,
        raw_message TEXT NOT NULL,
        parsed_data JSONB NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE INDEX IF NOT EXISTS {idx_hash} ON {table}(content_hash);
    CREATE INDEX IF NOT EXISTS {idx_date} ON {table}(message_date);
    """).format(
        table=table_name,
        idx_hash=idx_hash_name,
        idx_date=idx_date_name,
    )

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(create_table_sql)
            logger.info(f"Table '{schema_name}.{TABLE_NAME}' and indexes initialized")


def init_db() -> None:
    """Initialize database, schema, and table - create if they don't exist."""
    schema_name = config.DATABASE_SCHEMA

    # Step 1: Ensure database exists (best-effort, may fail if insufficient permissions)
    try:
        create_database_if_not_exists()
    except Exception as e:
        logger.warning(
            f"Could not create database (may already exist or insufficient permissions): {e}"
        )

    # Step 2: Ensure connection pool exists
    try:
        get_pool()
    except Exception as e:
        logger.error(f"Failed to create connection pool: {e}")
        raise

    # Step 3: Ensure schema exists (best-effort)
    try:
        create_schema_if_not_exists(schema_name)
    except Exception as e:
        logger.warning(f"Could not create schema '{schema_name}': {e}")

    # Step 4: Ensure table and indexes exist
    try:
        _create_table_and_indexes(schema_name)
    except Exception as e:
        logger.error(f"Failed to initialize table: {e}")
        raise


def check_exists(content_hash: str) -> bool:
    """Check if a message with the given content hash already exists (idempotency check)."""
    logger.debug(f"Checking if message exists: {content_hash[:16]}...")

    schema_name = config.DATABASE_SCHEMA
    table_name = _get_table_identifier(schema_name)

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT 1 FROM {} WHERE content_hash = %s").format(
                        table_name
                    ),
                    (content_hash,),
                )
                exists = cur.fetchone() is not None
                logger.debug(f"Message exists: {exists}")
                return exists
    except Exception as e:
        logger.error(f"Failed to check message existence: {e}")
        raise


def save_message(
    content_hash: str,
    message_date: str,
    raw_message: str,
    parsed_data: dict,
) -> None:
    """Save a new consumption message to the database."""
    logger.info(f"Saving message to database: {content_hash[:16]}...")

    schema_name = config.DATABASE_SCHEMA
    table_name = _get_table_identifier(schema_name)

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                    INSERT INTO {} 
                    (content_hash, message_date, raw_message, parsed_data)
                    VALUES (%s, %s, %s, %s)
                    """).format(table_name),
                    (
                        content_hash,
                        message_date,
                        raw_message,
                        json.dumps(parsed_data),
                    ),
                )
                logger.info("Message saved successfully")
    except psycopg2.IntegrityError as e:
        logger.warning(f"Message already exists (integrity error): {e}")
        raise ValueError("Message already exists") from e
    except Exception as e:
        logger.error(f"Failed to save message: {e}")
        raise
