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
export AWS_REGION="us-west-2"
```

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

### Testing with debug client on prod servers

1. Make sure you have the `uv` package installed (https://docs.astral.sh/uv/getting-started/installation/)
2. `uv run agent/api/agent_server/agent_api_client.py --host prod-agent-service-alb-999031216.us-west-2.elb.amazonaws.com --port 80` (or change the host if needed);
3. In the client, prompt for your app.
4. Waste some time, get some tea.
5. After getting a large output, use `/apply`
6. There will be a new dir in the output, open new tab and `cd` there.
7. `docker compose up`. Optionally you can use your other DB: set env variable `DATABASE_URL=<your_db_url>`; otherwise we use postgres in docker.
8. Go to `localhost:80`


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

## Commands

All the commands are run using `uv` from `agent` directory.

```
uv run test  # run all tests
uv run test_e2e  # only run e2e test
uv run lint   # lint and format the code
uv run update_cache  # update the LLM cache, required for new prompts or generation logic changes
uv run generate "my app description" # generate an app from scratch using full pipeline, similar to e2e test
```
