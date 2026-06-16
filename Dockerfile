FROM python:3.11-slim

# Install system dependencies (FFmpeg is required for video remuxing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency configuration
COPY requirements.txt .

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend and frontend source files
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Create a folder for temporary processing files
RUN mkdir -p /app/temp_processing

# Expose port
EXPOSE 8000

# Set environment variables
ENV MAX_UPLOAD_SIZE_MB=500
ENV TEMP_DIR=/app/temp_processing

# Run FastAPI app with Uvicorn
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
