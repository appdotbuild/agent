FROM oven/bun:1

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

# Build the server
RUN cd server && bun run build

# Expose the server port
EXPOSE 2022

# Run the server (adjust the path if needed)
CMD ["node", "server/dist/src/index.js"]