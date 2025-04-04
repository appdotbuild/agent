# Use Bun as the base image
FROM oven/bun:1

# Set working directory
WORKDIR /app/client

# Copy client package.json
COPY client/package.json ./

# Copy root package.json and lockfile if needed for dependencies
COPY package.json bun.lockb /app/

# Install dependencies
RUN bun install

# Copy client source files
COPY client/ ./

# Expose dev server port
EXPOSE 5173

# Run client dev server with host set to 0.0.0.0 to allow external access
CMD bun run dev