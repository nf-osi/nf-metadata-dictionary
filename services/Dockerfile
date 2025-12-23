FROM python:3.10-slim

LABEL maintainer="NF-OSI"
LABEL description="Tooltip/reference service for NF research tools"

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service code
COPY tooltip_service.py .

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8000/health').raise_for_status()"

# Run service
CMD ["python", "tooltip_service.py"]
