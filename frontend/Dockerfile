FROM node:22-alpine

WORKDIR /app

# Install dependencies first (for better caching)
COPY frontend/package*.json ./
RUN npm install

# Copy source code
COPY frontend/ ./

# Expose port
EXPOSE 5173

# Start the dev server exposed to host
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
