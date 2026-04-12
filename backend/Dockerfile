FROM node:20-slim

# Install Doppler CLI
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg && \
    curl -sLf --retry 3 --tlsv1.2 --proto "=https" \
    'https://packages.doppler.com/public/cli/gpg.DE2A7741A397C129.key' | \
    gpg --dearmor -o /usr/share/keyrings/doppler-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/doppler-archive-keyring.gpg] https://packages.doppler.com/public/cli/deb/debian any-version main" \
    > /etc/apt/sources.list.d/doppler-cli.list && \
    apt-get update && apt-get install -y doppler && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

COPY . .

# Build TypeScript
RUN npm install --include=dev && npx tsc && npm prune --omit=dev

EXPOSE 3001

# Doppler injects env vars from the service token set in Railway
ENTRYPOINT ["doppler", "run", "--"]
CMD ["node", "dist/server.js"]
