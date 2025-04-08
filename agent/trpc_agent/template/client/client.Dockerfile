# Build stage
FROM oven/bun:1 as builder

# Set working directory
WORKDIR /app

# Copy package.json and lockfile
COPY package.json bun.lockb ./

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
FROM nginx:alpine

WORKDIR /usr/share/nginx/
RUN rm -rf html
RUN mkdir html

# Copy your existing nginx configuration
COPY ./client/nginx/nginx.conf /etc/nginx/conf.d/default.conf

# Copy the built client files
COPY --from=builder /app/client/dist /usr/share/nginx/html

ENTRYPOINT ["nginx", "-g", "daemon off;"]