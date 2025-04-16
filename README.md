# App Creation Framework

See agent/README.md for details on the framework.

## Development Environment

### AWS SSO Configuration

1. Configure AWS SSO in `~/.aws/config`:
```ini
[profile dev]
sso_session = dev_agent
sso_account_id = 361769577597
sso_role_name = Sandbox
region = us-west-2
output = json

[sso-session dev_agent]
sso_start_url = https://neondb.awsapps.com/start
sso_region = eu-central-1
sso_registration_scopes = sso:account:access
```

2. Authenticate:
```bash
aws sso login --profile dev
```

In case of access issues, make sure you have access to the AWS sandbox account.

3. For local development:
```bash
export AWS_PROFILE=dev
```

4. For running compilation in containers, first run:
```bash
./agent/prepare_containers.sh
```
DockerSandboxTest python notebook contains sample usage.

## Basic Usage

### LLM-Guided Generation with MCP

The framework exposes four high-level tools for LLM-guided application generation through MCP (Model Control Plane):

1. **start_fsm**: Initialize the state machine with your application description
   ```
   Input: { "app_description": "Description of your application" }
   ```

2. **confirm_state**: Accept the current output and move to the next state
   ```
   Input: {}
   ```

3. **provide_feedback**: Submit feedback to revise the current component
   ```
   Input: {
     "feedback": "Your detailed feedback",
     "component_name": "Optional specific component name"
   }
   ```

4. **complete_fsm**: Finalize and return all generated artifacts
   ```
   Input: {}
   ```

## Environment Variables

```env
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
AWS_PROFILE=dev
AWS_REGION=us-west-2
```

### VCR Testing

We use VCR for testing LLM calls. VCR records LLM completions and saves them to a cache file, allowing us to replay them in tests. This is useful for testing LLM interactions without making real API calls.

- **Record mode**: Makes real API calls, saves responses to cache
- **Replay mode**: Uses cached responses (default, used in CI)
- **Off mode**: No caching, direct API calls

Default usage (to run tests with cached responses):
```
LLM_VCR_CACHE_MODE=replay uv run pytest .
```

If you want to record new responses, use:

```
LLM_VCR_CACHE_MODE=record uv run pytest .
```
New responses should be recorded in case of prompt changes or other significant changes in the pipeline (e.g. template modification, adding new steps etc.). VCR cache is stored in ./agent/llm/llm_cache.json by default, and new version should be committed to the repository.

Additional evaluation tools:
- `bot_tester.py`: Evaluates generated bots by running full conversations and assessing results
- `analyze_errors.py`: Analyzes langfuse traces to identify error patterns and performance issues

(both are rotten and need to be updated)

## Linting and Formatting

CI requires code to be formatted and linted. Use `ruff` for linting and formatting:
```
uv run ruff check . --fix
```
