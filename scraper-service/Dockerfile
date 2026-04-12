FROM python:3.11-slim

# Install base system deps + Doppler CLI via install script
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg tesseract-ocr && \
    curl -Ls --tlsv1.2 --proto "=https" --retry 3 https://cli.doppler.com/install.sh | sh && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers + all system deps in one shot
# (playwright install --with-deps handles Debian version differences automatically)
RUN playwright install --with-deps chromium

COPY . .

EXPOSE 8000

# Doppler injects all env vars at runtime via the service token
# passed as DOPPLER_TOKEN by the container orchestrator
ENTRYPOINT ["doppler", "run", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
