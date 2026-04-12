FROM python:3.11-slim

# Install system deps for Tesseract OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers + all system deps in one shot
RUN playwright install --with-deps chromium

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
