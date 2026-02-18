"""Message parsing logic to extract consumption data."""

import hashlib
import logging
import re
from datetime import date

from .models import ConsumptionData, ParsedMessage

logger = logging.getLogger(__name__)

# German month names mapping
MONTH_MAP = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}

# Regex patterns for parsing
MONTH_YEAR_PATTERN = re.compile(
    r"(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s+(\d{4})",
    re.IGNORECASE,
)
UNIT_PATTERN = re.compile(r"(m³|kWh)")
CURRENT_VALUE_PATTERN = re.compile(r"(\d{4}):\s*(\d+[.,]\d+)\s*(m³|kWh)")
AVERAGE_PATTERN = re.compile(
    r"(?:Durchschnitt.*?|Heizung auf Basis.*?):\s*(\d+[.,]\d+)\s*(m³|kWh)",
    re.IGNORECASE,
)

# Section boundaries
SECTION_HEADERS = {"kaltwasser", "warmwasser", "heizung"}
SECTION_END_MARKER = "falls sie fragen"


def generate_content_hash(text: str) -> str:
    """Generate SHA256 hash of message content for idempotency."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_month_year(text: str) -> tuple[str, int]:
    """Extract month and year from message text."""
    match = MONTH_YEAR_PATTERN.search(text)
    if not match:
        raise ValueError("Could not find month and year in message")
    month = match.group(1)
    year = int(match.group(2))
    return month, year


def _extract_section_text(text: str, section_name: str) -> str:
    """Extract text content for a specific consumption section."""
    # Find section boundaries line-by-line to avoid cutting off
    # lines like "Heizung auf Basis ...", which belong to the Heizung section.
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower() == section_name.lower():
            start_idx = i + 1
            break

    if start_idx is None:
        raise ValueError(f"Could not find {section_name} section")

    collected: list[str] = []
    for line in lines[start_idx:]:
        normalized = line.strip().lower()
        if normalized in SECTION_HEADERS and normalized != section_name.lower():
            break
        if normalized.startswith(SECTION_END_MARKER):
            break
        collected.append(line)

    section_text = "\n".join(collected).strip()
    if not section_text:
        raise ValueError(f"Could not parse content for {section_name}")
    return section_text


def _parse_numeric_value(value_str: str) -> float:
    """Parse numeric value, handling German comma decimal separator."""
    return float(value_str.replace(",", "."))


def parse_consumption_section(text: str, section_name: str) -> ConsumptionData:
    """Parse a consumption section (Kaltwasser, Warmwasser, or Heizung)."""
    section_text = _extract_section_text(text, section_name)

    # Extract unit first (should be consistent within a section)
    unit_match = UNIT_PATTERN.search(section_text)
    if not unit_match:
        raise ValueError(f"Could not determine unit for {section_name}")
    unit = unit_match.group(1)

    # Extract current and previous year values
    # Format: "Year: value unit" - first occurrence is current month, second is previous year
    current_matches = list(CURRENT_VALUE_PATTERN.finditer(section_text))
    if len(current_matches) < 2:
        raise ValueError(
            f"Could not find both current month and previous year values for {section_name}"
        )
    current_value = _parse_numeric_value(current_matches[0].group(2))
    prev_value = _parse_numeric_value(current_matches[1].group(2))

    # Extract property average
    # HomeCase uses formats: "Durchschnitt der Liegenschaft ..." or "Heizung auf Basis ..."
    avg_match = AVERAGE_PATTERN.search(section_text)
    if not avg_match:
        raise ValueError(f"Could not find property average for {section_name}")
    avg_value = _parse_numeric_value(avg_match.group(1))

    return ConsumptionData(
        current_month=current_value,
        previous_year=prev_value,
        property_average=avg_value,
        unit=unit,
    )


def parse_message(raw_message: str) -> ParsedMessage:
    """Parse raw message text and extract all consumption data."""
    logger.debug("Parsing message content")

    # Generate content hash
    content_hash = generate_content_hash(raw_message)
    logger.debug(f"Generated content hash: {content_hash[:16]}...")

    # Extract month and year
    month, year = parse_month_year(raw_message)
    logger.debug(f"Extracted date: {month} {year}")

    # Convert month name to date
    month_num = MONTH_MAP[month.lower()]
    message_date = date(year, month_num, 1)  # Use first day of month

    # Parse each consumption type
    try:
        kaltwasser = parse_consumption_section(raw_message, "Kaltwasser")
        logger.debug(f"Parsed Kaltwasser: {kaltwasser.current_month} {kaltwasser.unit}")
    except Exception as e:
        logger.error(f"Failed to parse Kaltwasser: {e}")
        raise

    try:
        warmwasser = parse_consumption_section(raw_message, "Warmwasser")
        logger.debug(f"Parsed Warmwasser: {warmwasser.current_month} {warmwasser.unit}")
    except Exception as e:
        logger.error(f"Failed to parse Warmwasser: {e}")
        raise

    try:
        heizung = parse_consumption_section(raw_message, "Heizung")
        logger.debug(f"Parsed Heizung: {heizung.current_month} {heizung.unit}")
    except Exception as e:
        logger.error(f"Failed to parse Heizung: {e}")
        raise

    return ParsedMessage(
        month=month,
        year=year,
        message_date=message_date,
        kaltwasser=kaltwasser,
        warmwasser=warmwasser,
        heizung=heizung,
        raw_message=raw_message,
        content_hash=content_hash,
    )
