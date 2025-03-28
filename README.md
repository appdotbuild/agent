# Bot Creation Framework

A framework leveraging Amazon Bedrock and LLMs to generate production-ready TypeScript applications with natural language interfaces. Uses a sophisticated pipeline to generate type-safe code, database schemas, and natural language processing capabilities.

## Pipeline Architecture

![Pipeline Architecture](pipeline_architecture.png)

The framework implements a multi-stage generation pipeline:

1. **Natural Language Input**
   - Application description as entry point
   - Natural language requirements
   - Use case definitions

2. **Type Generation**
   ```typescript
   // Example TypeSpec Definition
   model Exercise {
       name: string
       sets: int32
       reps: int32
       weight?: float32
       equipment: Equipment
       targetMuscles: string[]
   }

   interface GymTracker {
       @llm_func(2)
       recordExercise(exercise: Exercise): void;
   }
   ```

3. **Database Schema Generation**
   ```typescript
   // Generated Drizzle Schema
   export const exerciseTable = pgTable("exercise", {
       id: integer("id").primaryKey().generatedAlwaysAsIdentity(),
       name: text("name").notNull(),
       sets: integer("sets").notNull(),
       reps: integer("reps").notNull(),
       weight: real("weight"),
       equipmentId: integer("equipment_id").references(() => equipmentTable.id)
   });
   ```

4. **Natural Language Processing**
   ```typescript
   // Function Router Example
   const router = new LLMFunctionRouter(client, [
       {
           name: "recordExercise",
           description: "Record a workout exercise with sets, reps, and weight",
           parameters: {
               type: "object",
               properties: {
                   name: { type: "string" },
                   sets: { type: "integer" },
                   reps: { type: "integer" }
               }
           }
       }
   ]);
   ```

5. **Business Logic Generation**
   ```typescript
   // Generated Handler
   const handle = async (exercise: Exercise): Promise<void> => {
       const [existingEquipment] = await db
           .select()
           .from(equipmentTable)
           .where(eq(equipmentTable.name, exercise.equipment.name))
           .limit(1);
       // ... implementation
   };
   ```

## Example Application

The included example demonstrates a gym tracking bot that:
- Processes natural language input for workout tracking
- Manages exercises and equipment
- Suggests personalized routines
- Tracks progress over time

```python
# Application Description
application_description = """
Bot that tracks my exercise routine in the gym, tracks progress and suggests new routines
for specific list of available equipment and time constraints.
""".strip()

# Generate TypeSpec
typespec = stages.typespec.parse_output(tsp_response.content[0].text)
```

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

#### Setup for Cursor

For Cursor users, register the MCP server:

```bash
python mcp_tools/setup_global_mcp.py
```

This registers an MCP server called "app-build" that Cursor can connect to for guided generation. Other clients may require different setup.

#### Testing with fsm_tools

You can test the FSM tools directly from the command line:

```bash
PYTHONPATH=$PYTHONPATH:./agent/ uv run python agent/fsm_tools.py "your app description"
```

This runs a guided generation session with the specified application description, allowing you to test the FSM tools without setting up MCP.

### Jupyter version

The Scratchpad notebook in `agent/` demonstrates the framework's capabilities:

1. Configure AWS client:
```python
client = AnthropicBedrock(
    aws_profile="dev",
    aws_region="us-west-2"
)
```

2. Define application behavior:
```python
application_description = """
Bot that tracks my exercise routine in the gym, tracks progress and suggests new routines
for specific list of available equipment and time constraints.
""".strip()
```

3. Execute generation pipeline:
```python
# Generate TypeSpec
typespec = stages.typespec.parse_output(tsp_response.content[0].text)

# Generate Schema
drizzle = stages.drizzle.parse_output(dzl_response.content[0].text)

# Generate Processors
pre_processors = {...}

# Generate Handlers
handlers = {...}
```

## Generated Application

The framework produces a TypeScript application with:

```
src/
├── common/
│   ├── crud.ts      # Database operations
│   ├── handler.ts   # Base handler types
│   └── llm.ts       # LLM integration
├── db/
│   └── schema/      # Generated Drizzle schema
├── logic/
│   ├── router.ts    # NLP routing
│   └── handlers/    # Business logic
└── main.ts
```

One could run it with `docker compose up` in the generated app.

## Environment Variables

```env
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
AWS_PROFILE=dev
AWS_REGION=us-west-2
```

## Type Safety

The framework enforces type safety through:
- TypeScript interfaces
- Drizzle ORM
- Runtime validation
- LLM function schemas

## Error Handling

No error handling yet.

## Testing

The framework includes comprehensive tests to ensure reliability:

```bash
# Run all tests
PYTHONPATH=./agent/ uv run pytest -vs agent/tests/
```

### End-to-End VCR Testing

There is a test for main usage scenario in agent/tests/test_end2end.py. It relies on LLM calls and has two modes:
- **Record mode**: Makes real API calls, saves responses to cache
- **Replay mode**: Uses cached responses (default, used in CI)

Default usage (just to check things are fine):

```
uv run pytest -vs agent/tests/test_end2end.py
```

If you want to record new responses, use:

```
PYTHONPATH=$PYTHONPATH:./agent uv run python agent/tests/test_end2end.py
```
New responses should be recorded in case of prompt changes or other significant changes in the pipeline (e.g. template modification, adding new steps etc.). VCR cache is stored in ./anthropic_cache.json by default, and new version should be committed to the repository.

Heads up: VCR cache recording may lead to imperfect record from the first run, because of non-deterministic nature of LLM API calls. In this case, you may need to run the test several times to get a good recording passing the test.

The test suite includes:
- **Server Tests**: API endpoint testing with request validation and error handling

Additional evaluation tools:
- `bot_tester.py`: Evaluates generated bots by running full conversations and assessing results
- `analyze_errors.py`: Analyzes langfuse traces to identify error patterns and performance issues

## Contributing

### VS Code Dev Container Setup (Optional)

Project includes DevContainer configuration for consistent development environment:

```json
// For format details, see https://aka.ms/devcontainer.json. For config options, see the
// README at: https://github.com/devcontainers/templates/tree/main/src/python
{
	"name": "Python 3",
	// Or use a Dockerfile or Docker Compose file. More info: https://containers.dev/guide/dockerfile
	"image": "mcr.microsoft.com/devcontainers/python:1-3.12-bullseye",

	"runArgs": [
		"--network=neon"
	],

    "features": {
		"ghcr.io/devcontainers/features/rust:1": {
			"version": "1.84"
		},
		"ghcr.io/devcontainers/features/node:1": {
			"version": "20.11"
		},
		"ghcr.io/devcontainers/features/aws-cli:1.1.0": {},
		"ghcr.io/devcontainers/features/docker-outside-of-docker:1": {},
		"ghcr.io/devcontainers/features/common-utils:2": {
			"username": "automatic",
			"uid": "automatic",
			"gid": "automatic",
			"installZsh": true,
			"installOhMyZsh": true,
			"upgradePackages": true
		},
		"ghcr.io/devcontainers/features/git:1": {}
	},
	"customizations": {
		"vscode": {
			"settings": {
				"files.watcherExclude": {
					"**/target/**": true,
					"**/.venv/**": true,
					"**/.git/objects/**": true,
					"**/.git/subtree-cache/**": true,
					"**/node_modules/*/**": true
				}
			},
			"extensions": [
				"ms-azuretools.vscode-docker",
				"Github.copilot",
				"ms-toolsai.jupyter",
				"ms-python.black-formatter",
				"typespec.typespec-vscode"
			]
		}
	}

	// Features to add to the dev container. More info: https://containers.dev/features.
	// "features": {},

	// Use 'forwardPorts' to make a list of ports inside the container available locally.
	// "forwardPorts": [],

	// Use 'postCreateCommand' to run commands after the container is created.
	// "postCreateCommand": "pip3 install --user -r requirements.txt",

	// Configure tool-specific properties.
	// "customizations": {},

	// Uncomment to connect as root instead. More info: https://aka.ms/dev-containers-non-root.
	// "remoteUser": "root"
}
```
