FROM python:3.11-slim

# Install base system deps + Doppler CLI in a single layer
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg tesseract-ocr && \
    curl -sLf --retry 3 --tlsv1.2 --proto "=https" \
    'https://packages.doppler.com/public/cli/gpg.DE2A7741A397C129.key' | \
    gpg --dearmor -o /usr/share/keyrings/doppler-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/doppler-archive-keyring.gpg] https://packages.doppler.com/public/cli/deb/debian any-version main" \
    > /etc/apt/sources.list.d/doppler-cli.list && \
    apt-get update && apt-get install -y doppler && \
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
