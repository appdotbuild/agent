# For local development only! Do not use for deployment, it is not guaranteed to work.

FROM oven/bun:latest

WORKDIR /app

COPY package.json ./
RUN bun install

COPY . .

RUN chmod +x src/helpers/reset.ts src/main.ts

# use shell to execute multiple commands - should be replaced with `bun start` later 
CMD ["/bin/sh", "-c", "bun run src/helpers/reset.ts && bun run db:push && bun src/main.ts"]
