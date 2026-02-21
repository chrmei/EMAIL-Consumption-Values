"""Main application entrypoint - orchestrates the entire workflow.

kind: script
lockfile: |
  requests>=2.31.0
  beautifulsoup4>=4.12.0
  python-dotenv>=1.0.0
  psycopg2-binary>=2.9.9
  pydantic>=2.0.0
"""

import logging
import sys

from .config import config
from .database import check_exists, init_db, save_message
from .email import format_email_body, send_email
from .parser import parse_message
from .scraper import HomeCaseScraper

# Default message fetch limit
DEFAULT_MESSAGE_LIMIT = 24


def setup_logging() -> None:
    """Configure logging based on environment variables."""
    log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers
    root_logger.handlers.clear()

    # Add console handler (stdout) for container/Kestra compatibility
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Add file handler if LOG_FILE is set
    if config.LOG_FILE:
        file_handler = logging.FileHandler(config.LOG_FILE)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Set library loggers to WARNING to avoid noise
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def main() -> int:
    """Main application workflow."""
    logger = logging.getLogger(__name__)

    try:
        # Setup logging
        setup_logging()
        logger.info("Starting Unofficial HomeCase Automation")

        # Validate configuration
        logger.debug("Validating configuration")
        config.validate()

        # Initialize database
        logger.info("Initializing database")
        init_db()

        # Scrape and parse messages
        logger.info("Starting web scraping")
        with HomeCaseScraper() as scraper:
            scraper.login()
            scraper.navigate_to_messages()
            raw_messages = scraper.find_consumption_messages(
                limit=DEFAULT_MESSAGE_LIMIT
            )

        if not raw_messages:
            logger.warning("No consumption messages found")
            return (
                2  # Exit code 2: no message found (already processed or not available)
            )

        logger.info("Found %d candidate consumption message(s)", len(raw_messages))
        new_messages = []

        for raw_message in raw_messages:
            logger.info("Parsing message content")
            parsed_message = parse_message(raw_message)
            logger.info(
                "Parsed message for %s %s", parsed_message.month, parsed_message.year
            )

            # Check if already processed (idempotency)
            if check_exists(parsed_message.content_hash):
                logger.info(
                    "Message for %s %s already processed - skipping",
                    parsed_message.month,
                    parsed_message.year,
                )
                continue

            # Save to database
            logger.info("Saving message to database")
            save_message(
                content_hash=parsed_message.content_hash,
                message_date=parsed_message.message_date.isoformat(),
                raw_message=parsed_message.raw_message,
                parsed_data=parsed_message.to_dict(),
            )
            new_messages.append(parsed_message)

        if not new_messages:
            logger.info("All fetched messages were already processed")
            return 2  # Exit code 2: no new messages

        # Send emails for newly saved messages.
        logger.info(
            "Preparing email notifications for %d new message(s)", len(new_messages)
        )
        recipients = [email.strip() for email in config.EMAIL_TO.split(",")]
        cc_recipients = None
        if config.EMAIL_TO_CC:
            cc_recipients = [email.strip() for email in config.EMAIL_TO_CC.split(",")]
        for parsed_message in new_messages:
            subject = (
                f"Verbrauchswerte für {parsed_message.month} {parsed_message.year}"
            )
            body = format_email_body(parsed_message, config.TENANT_GREETING)
            send_email(recipients, subject, body, cc=cc_recipients)

        logger.info(
            "Workflow completed successfully (%d new message(s))", len(new_messages)
        )
        return 0  # Exit code 0: success

    except ValueError as e:
        logger.error(f"Configuration or validation error: {e}")
        return 1
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return 1  # Exit code 1: error


if __name__ == "__main__":
    sys.exit(main())
