# Full-stack codegen

Generates full stack apps using trpc + shadcn components.

> **Important**: The implementation in `stash_bot` is deprecated and will be removed in a future version.
> New development should use the `trpc_agent` implementation.

## Installation:

1. Install [dagger](https://docs.dagger.io/install/)
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/)
3. Set Anthropic key variable `ANTHROPIC_API_KEY=sk-ant-api`

## Usage:

`uv run generate "my app description"`

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

### Running with docker - doesn't have hot reload

`docker compose up --build`
