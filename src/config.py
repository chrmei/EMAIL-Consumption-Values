"""Configuration management from environment variables."""

import os
from typing import Optional

from dotenv import load_dotenv

# Load environment variables from .env file if it exists (optional)
# This allows the app to work with environment variables set directly
# without requiring a .env file. The override=False ensures that environment variables
# already set take precedence over .env file values.
load_dotenv(override=False)


class Config:
    """Application configuration loaded from environment variables."""

    # HomeCase portal credentials
    HOMECASE_URL_LOGIN: str = os.getenv("HOMECASE_URL_LOGIN", "")
    HOMECASE_URL_MESSAGES: str = os.getenv("HOMECASE_URL_MESSAGES", "")
    HOMECASE_USERNAME: str = os.getenv("HOMECASE_USERNAME", "")
    HOMECASE_PASSWORD: str = os.getenv("HOMECASE_PASSWORD", "")
    REQUEST_DELAY_SECONDS: float = float(os.getenv("REQUEST_DELAY_SECONDS", "0.5"))

    # Database configuration
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    DATABASE_SCHEMA: str = os.getenv("DATABASE_SCHEMA", "public")

    # SMTP configuration
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")

    # Email configuration
    EMAIL_FROM: str = os.getenv("EMAIL_FROM", "")
    EMAIL_TO: str = os.getenv("EMAIL_TO", "")
    EMAIL_TO_CC: Optional[str] = os.getenv("EMAIL_TO_CC", None)
    TENANT_GREETING: str = os.getenv("TENANT_GREETING", "Liebe Mieterin")
    EMAIL_SIGNATURE: Optional[str] = os.getenv("EMAIL_SIGNATURE", None)

    # Logging configuration
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: Optional[str] = os.getenv("LOG_FILE", None)

    def validate(self) -> None:
        """Validate that all required configuration values are set."""
        required_fields = [
            ("HOMECASE_URL_LOGIN", self.HOMECASE_URL_LOGIN),
            ("HOMECASE_URL_MESSAGES", self.HOMECASE_URL_MESSAGES),
            ("HOMECASE_USERNAME", self.HOMECASE_USERNAME),
            ("HOMECASE_PASSWORD", self.HOMECASE_PASSWORD),
            ("DATABASE_URL", self.DATABASE_URL),
            ("SMTP_HOST", self.SMTP_HOST),
            ("SMTP_USER", self.SMTP_USER),
            ("SMTP_PASSWORD", self.SMTP_PASSWORD),
            ("EMAIL_TO", self.EMAIL_TO),
        ]

        missing = [name for name, value in required_fields if not value]
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")
        if self.REQUEST_DELAY_SECONDS < 0:
            raise ValueError("REQUEST_DELAY_SECONDS must be >= 0")


# Global config instance
config = Config()
