FROM python:3.10-slim

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app && \
    chown -R appuser:appuser /app

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/

# Set PYTHONPATH to ensure Python can find the src module
ENV PYTHONPATH=/app

# Switch to non-root user
USER appuser

# Default command
CMD ["python", "-m", "src.main"]
