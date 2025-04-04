# Use Bun as the base image
FROM oven/bun:1

# Set working directory directly to server directory
WORKDIR /app/server

# Copy server package.json
COPY server/package.json ./

# Copy root package.json and lockfile if needed for dependencies
COPY package.json bun.lockb /app/

# Install dependencies
RUN bun install

# Copy server source files
COPY server/ ./

# Expose the server port
EXPOSE 2022

# Run migrations the server in development mode
CMD bun run db:push && bun run dev