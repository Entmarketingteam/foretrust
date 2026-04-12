FROM node:20-slim

# Install Doppler CLI via install script (handles cert + key differences across distros)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && \
    curl -Ls --tlsv1.2 --proto "=https" --retry 3 https://cli.doppler.com/install.sh | sh && \
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
