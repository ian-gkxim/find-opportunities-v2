FROM node:20-alpine

WORKDIR /app

# Install dependencies
COPY package.json package-lock.json ./
RUN npm ci

# Copy source
COPY . .

# Build the Next.js app
RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "start"]
