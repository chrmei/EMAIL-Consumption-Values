"""Data models using Pydantic for type safety and validation."""

from datetime import date

from pydantic import BaseModel, Field, field_validator


class ConsumptionData(BaseModel):
    """Structured consumption values for a single utility type."""

    current_month: float = Field(..., description="Current month value")
    previous_year: float = Field(..., description="Previous year value")
    property_average: float = Field(..., description="Property average value")
    unit: str = Field(..., description="Unit of measurement (m³ or kWh)")

    @field_validator("current_month", "previous_year", "property_average")
    @classmethod
    def validate_positive(cls, v: float) -> float:
        """Ensure values are non-negative."""
        if v < 0:
            raise ValueError("Consumption values must be non-negative")
        return v


class ParsedMessage(BaseModel):
    """Complete parsed message with metadata."""

    month: str = Field(..., description="Month name (e.g., 'Dezember')")
    year: int = Field(..., description="Year (e.g., 2025)")
    message_date: date = Field(..., description="Date of the message")
    kaltwasser: ConsumptionData = Field(..., description="Cold water consumption")
    warmwasser: ConsumptionData = Field(..., description="Hot water consumption")
    heizung: ConsumptionData = Field(..., description="Heating consumption")
    raw_message: str = Field(..., description="Original raw message text")
    content_hash: str = Field(..., description="SHA256 hash of message content")

    @field_validator("year")
    @classmethod
    def validate_year(cls, v: int) -> int:
        """Ensure year is reasonable."""
        if v < 2000 or v > 2100:
            raise ValueError("Year must be between 2000 and 2100")
        return v

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "month": self.month,
            "year": self.year,
            "message_date": self.message_date.isoformat(),
            "kaltwasser": {
                "current_month": self.kaltwasser.current_month,
                "previous_year": self.kaltwasser.previous_year,
                "property_average": self.kaltwasser.property_average,
                "unit": self.kaltwasser.unit,
            },
            "warmwasser": {
                "current_month": self.warmwasser.current_month,
                "previous_year": self.warmwasser.previous_year,
                "property_average": self.warmwasser.property_average,
                "unit": self.warmwasser.unit,
            },
            "heizung": {
                "current_month": self.heizung.current_month,
                "previous_year": self.heizung.previous_year,
                "property_average": self.heizung.property_average,
                "unit": self.heizung.unit,
            },
        }
