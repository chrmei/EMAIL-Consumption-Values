"""SMTP email sending functionality."""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional

from .config import config
from .models import ConsumptionData, ParsedMessage

logger = logging.getLogger(__name__)

# SMTP configuration constants
SMTP_PORT_SSL = 465
SMTP_PORT_STARTTLS = 587


def format_number_german(value: float) -> str:
    """Format number in German format (comma as decimal separator)."""
    # Format with 3 decimal places, then replace period with comma
    # German format uses comma for decimal separator
    formatted = f"{value:.3f}".replace(".", ",")
    return formatted


def _format_consumption_section(
    section_name: str,
    data: ConsumptionData,
    month: str,
    year: int,
    is_heating: bool = False,
) -> str:
    """Format a single consumption section (Kaltwasser, Warmwasser, or Heizung)."""
    current = format_number_german(data.current_month)
    previous = format_number_german(data.previous_year)
    average = format_number_german(data.property_average)

    if is_heating:
        avg_label = (
            f"Heizung auf Basis des Durchschnitts der Liegenschaft {month} {year}"
        )
        avg_note = "(Gesamtverbrauch Heizung / Gesamt Wohnfläche x Wohnfläche Einheit)"
    else:
        avg_label = f"Durchschnitt der Liegenschaft {month} {year}"
        avg_note = "(Gesamtverbrauch Liegenschaft / Anzahl Einheiten)"

    return f"""{section_name}
{month} {year}: {current} {data.unit}
{month} {year - 1}: {previous} {data.unit}
{avg_label}: {average} {data.unit} {avg_note}"""


def _format_email_signature() -> str:
    """Format email signature from configuration."""
    if config.EMAIL_SIGNATURE:
        # Convert literal \n sequences to actual newlines
        return config.EMAIL_SIGNATURE.replace("\\n", "\n")
    # Return empty string if no signature is configured
    return ""


def format_email_body(parsed_message: ParsedMessage, tenant_greeting: str) -> str:
    """Format email body from parsed consumption data."""
    month = parsed_message.month
    year = parsed_message.year

    kaltwasser_section = _format_consumption_section(
        "Kaltwasser", parsed_message.kaltwasser, month, year
    )
    warmwasser_section = _format_consumption_section(
        "Warmwasser", parsed_message.warmwasser, month, year
    )
    heizung_section = _format_consumption_section(
        "Heizung", parsed_message.heizung, month, year, is_heating=True
    )

    signature = _format_email_signature()
    body = f"""{tenant_greeting}

hier deine Verbrauchswerte für den Monat {month} {year}:

{kaltwasser_section}

{warmwasser_section}

{heizung_section}"""

    if signature:
        body += f"\n\n{signature}"

    return body


def send_email(
    recipients: List[str], subject: str, body: str, cc: Optional[List[str]] = None
) -> None:
    """
    Send email via SMTP.

    Supports Posteo email configuration:
    - Port 587: STARTTLS (recommended)
    - Port 465: SSL/TLS (alternative)

    Posteo requires:
    - Server: posteo.de or smtp.posteo.de
    - Authentication: Required (use application password)
    - Encryption: TLS/STARTTLS mandatory

    Args:
        recipients: List of primary recipient email addresses
        subject: Email subject line
        body: Email body text
        cc: Optional list of CC recipient email addresses
    """
    all_recipients = recipients.copy()
    if cc:
        all_recipients.extend(cc)

    logger.info(
        f"Sending email to {len(recipients)} recipient(s)"
        + (f" with {len(cc)} CC recipient(s)" if cc else "")
    )

    # Create message
    msg = MIMEMultipart()
    msg["From"] = config.EMAIL_FROM
    msg["To"] = ", ".join(recipients)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject

    # Attach body
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        # Connect to SMTP server
        logger.debug(
            f"Connecting to SMTP server: {config.SMTP_HOST}:{config.SMTP_PORT}"
        )

        # Posteo port configuration:
        # - Port 465: SSL/TLS (use SMTP_SSL)
        # - Port 587: STARTTLS (use SMTP + starttls())
        if config.SMTP_PORT == SMTP_PORT_SSL:
            server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT)
            logger.debug("Using SSL/TLS encryption (port 465)")
        else:
            server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT)
            server.starttls()
            logger.debug("Using STARTTLS encryption")

        # Login (required for Posteo SMTP)
        logger.debug("Authenticating with SMTP server")
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)

        # Send email (sendmail requires all recipients including CC)
        text = msg.as_string()
        server.sendmail(config.EMAIL_FROM, all_recipients, text)
        server.quit()

        logger.info("Email sent successfully")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        raise
