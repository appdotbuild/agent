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

### Python script version

Those who prefer using Python scripts directly to use the debugger and other fancy features can use the following script:

```bash
cd agent
python debug.py "your app description" /optional/path/to/final_output
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

## Contributing

### Nix Setup (Recommended)

1. Install [Nix](https://nixos.org/nix/)

   ```
   sh <(curl -L https://nixos.org/nix/install)
   ```

2. Install and setup [Direnv](https://direnv.net/)

   ```
   # Install direnv
   curl -sfL https://direnv.net/install.sh | bash

   # Load nix environment
   direnv allow
   ```

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
