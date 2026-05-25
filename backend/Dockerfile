FROM node:20-slim

WORKDIR /app

# Gemini Ultra CLI (OAuth subscription — not API key billing)
RUN npm install -g @google/gemini-cli

ENV GEMINI_BIN=gemini
ENV GEMINI_MODEL=gemini-2.5-flash
ENV GEMINI_CLI_HOME=/root/.gemini
ENV GEMINI_CLI_USER_HOME=/root

COPY package.json ./
RUN npm install --omit=dev

COPY . .

# Build TypeScript
RUN npm install --include=dev && npx tsc && npm prune --omit=dev

EXPOSE 3001

CMD ["node", "dist/server.js"]
