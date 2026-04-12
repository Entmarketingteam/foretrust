FROM node:20-slim

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

COPY . .

# Build TypeScript
RUN npm install --include=dev && npx tsc && npm prune --omit=dev

EXPOSE 3001

CMD ["node", "dist/server.js"]
