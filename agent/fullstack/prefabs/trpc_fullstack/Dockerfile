# Build stage for both client and server
FROM oven/bun:1 as builder

# Set working directory
WORKDIR /app

# Copy package files
COPY package.json bun.lockb ./
COPY client/package.json ./client/
COPY server/package.json ./server/

# Install dependencies
RUN bun install --frozen-lockfile

# Copy source code
COPY . .

# Build client and server
RUN cd client && bun run build
RUN cd server && bun run build

# Final stage - use oven/bun as base to avoid compatibility issues
FROM oven/bun:1

# Install nginx directly
RUN apt-get update && apt-get install -y nginx && apt-get clean

# Copy frontend files
COPY --from=builder /app/client/dist /usr/share/nginx/html
COPY ./client/nginx/nginx.conf /etc/nginx/conf.d/default.conf

# Modify nginx config - in fly it needs to be 8080
RUN sed -i 's/listen 80;/listen 8080;/g' /etc/nginx/conf.d/default.conf
RUN sed -i 's/app-backend/localhost/g' /etc/nginx/conf.d/default.conf

# Copy backend files
COPY --from=builder /app/server /app/server
COPY --from=builder /app/node_modules /app/node_modules

# Create a simple start script
RUN echo '#!/bin/sh\nnginx &\ncd /app/server && bun run start:build' > /start.sh
RUN chmod +x /start.sh

# Expose port
EXPOSE 8080

# Use the script
CMD ["/start.sh"]