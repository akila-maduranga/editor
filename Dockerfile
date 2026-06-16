FROM python:3.11-slim

# Install FFmpeg for remux stage
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/

RUN mkdir -p /app/temp_processing

EXPOSE 8000

ENV MAX_UPLOAD_SIZE_MB=500
ENV TEMP_DIR=/app/temp_processing

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
