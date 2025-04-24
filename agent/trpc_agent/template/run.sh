lsof -ti:2022 | xargs kill -9

echo Assuming postgres is running on port 5432
#docker stop postgres && docker rm postgres && docker run --name postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_USER=postgres -e POSTGRES_DB=postgres -p 5432:5432 -d postgres:latest

# Pause to ensure the database is ready
#echo "Waiting for PostgreSQL to start..."
#sleep 5
#echo "Continuing setup..."


DATABASE_URL=postgres://postgres:postgres@localhost:5432/postgres && bun run --filter app-build-server db:push

bun install

DATABASE_URL=postgres://postgres:postgres@localhost:5432/postgres && bun run dev:all