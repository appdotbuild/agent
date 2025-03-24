# Full-stack codegen

Generates full stack apps using trpc + shadcn components.  

## Installation:

1. Install [dagger](https://docs.dagger.io/install/)
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/)
3. Set Anthropic key variable `ANTHROPIC_API_KEY=sk-ant-api`

## Usage:

`uv run main.py --num_beams 1 --export_dir demo_app`

### Running generated code

Chande directory:

`cd demo_app`

Configure postgres address:

`export DATABASE_URL=postgres://postgres:postgres@postgres:5432/postgres`

Apply migrations:

`bun run db:push`

Start the app:

`bun run dev:all`

(Optional) resetting the database:

`bun run server/src/helpers/reset.ts `
