FROM python:3.11-slim

# Install system deps for Tesseract OCR + Chromium runtime (Debian 12 bookworm)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl tesseract-ocr \
    # Chromium/Playwright runtime dependencies for Debian 12
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libxkbcommon0 libatspi2.0-0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2t64 \
    fonts-liberation fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright chromium to a known path that persists in the image
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.playwright
RUN playwright install chromium

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
