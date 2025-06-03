<div align="center">
  <img src="logo.png" alt="app.build logo" width="150">
</div>

# app.build (agent)

**app.build** is an open-source AI agent for generating production-ready full-stack applications from a single prompt.

## What it builds

- **Full-stack web apps** with React, Vite, and Fastify
- **Neon Postgres database** provisioned instantly via API
- **Authentication** via Neon Auth
- **End-to-end tests** written in Playwright
- **GitHub repository** with complete source code
- **CI/CD and deployment** via Koyeb
- **Automatic validation** with ESLint, TypeScript, and runtime verification

## Try it

```bash
npx @app.build/cli
```

## Architecture

This agent doesn't generate entire applications at once. Instead, it breaks down app creation into small, well-scoped tasks that run in isolated sandboxes:

1. **Database schema generation** - Creates typed database models
2. **API handler logic** - Builds validated Fastify routes
3. **Frontend components** - Generates React UI with proper typing
4. **Test suite creation** - Writes comprehensive Playwright tests

Each task is validated independently using ESLint, TypeScript compilation, test execution, and runtime logs before being accepted.

## Repository structure

This is the **agent** repository containing the core code generation engine and runtime environment. The CLI and platform code are available in the [platform repository](link-to-platform-repo).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and contribution guidelines.
See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and contribution guidelines.

## Running locally

Local development instructions are available in [CONTRIBUTING.md](CONTRIBUTING.md).

---
Local development instructions are available in [CONTRIBUTING.md](CONTRIBUTING.md).

---

Built to showcase agent-native infrastructure patterns. Fork it, remix it, use it as a reference for your own projects.
Built to showcase agent-native infrastructure patterns. Fork it, remix it, use it as a reference for your own projects.