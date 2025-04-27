# Build stage
FROM oven/bun:1.2.2-alpine AS builder

# Set working directory
WORKDIR /app

# Copy package.json and lockfile
COPY package.json bun.lock ./

# Create directories for client and server
RUN mkdir -p client server

# Copy package.json for client and server
COPY client/package.json ./client/
COPY server/package.json ./server/

# Install all dependencies
RUN bun install --frozen-lockfile

# Copy the entire project
COPY . .

# Build client
RUN cd client && bun run build

# Production stage for frontend
FROM caddy:alpine

# Install curl for healthcheck
RUN apk add --no-cache curl

WORKDIR /srv

# Copy the built client files
COPY --from=builder /app/client/dist /srv

# Create Caddyfile mimicking previous Nginx config
RUN cat <<EOF > /etc/caddy/Caddyfile
:80 {
    root * /srv

    # Security Headers
    header {
        X-Frame-Options "SAMEORIGIN"
        X-XSS-Protection "1; mode=block"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "strict-origin-when-cross-origin"
        # Content-Security-Policy "default-src \'self\'; script-src \'self\' \'unsafe-inline\'; img-src \'self\' data:; style-src \'self\' \'unsafe-inline\'; font-src \'self\'; connect-src \'self\' app-backend:2022" # Adjust CSP if needed, especially connect-src
    }

    # API Proxy
    route /api/* {
        uri strip_prefix /api
        reverse_proxy app-backend:2022 {
            # Forward common headers like Nginx did
            header_up Host {host}
            header_up X-Real-IP {remote_ip}
            header_up X-Forwarded-For {remote_ip}
            header_up X-Forwarded-Proto {scheme}
            # Disable buffering like nginx's proxy_buffering off;
            flush_interval -1
        }
    }

    # Handle SPA routing before serving files
    try_files {path} {path}/ /index.html

    # Serve static files
    file_server
}
EOF

ENTRYPOINT ["caddy", "run", "--config", "/etc/caddy/Caddyfile"]