# Full-stack codegen

Generates full stack apps using trpc + shadcn components.

## Installation:

1. Install [dagger](https://docs.dagger.io/install/)
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/)
3. Set Anthropic key variable `ANTHROPIC_API_KEY=sk-ant-api`

## Usage:

`uv run main.py --num_beams 1 --export_dir demo_app`

### Running generated code

Change directory:

`cd demo_app`

Configure postgres address:

`export DATABASE_URL=postgres://postgres:postgres@postgres:5432/postgres`

Start the app:

`bun run dev:all`

(Optional) resetting the database:

`bun run server/src/helpers/reset.ts `

### Running with docker - doesn't have hot reload

Change directory:

`cd demo_app`

Run through docker compose:
`docker compose up --build`

This will apply DB migrations and start the server/client.

Just open the browser and go to `http://localhost:80`

### Deploying to fly

Change directory:

`cd demo_app`

Run the following command to deploy the app:

`fly deploy` - this will use the Dockerfile in the root to build the app.

If you don't have a fly.toml file, you can create one by running:

`fly launch`

This will create a new app and deploy it to fly.
