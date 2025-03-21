from typing import TypedDict, NotRequired
import os
import enum
from dagger import dag
from anthropic import AsyncAnthropicBedrock
from anthropic.types import TextBlock, MessageParam, ContentBlockParam
import logic
import playbooks
import statemachine
from workspace import Workspace
from shared_fsm import BFSExpandActor, NodeData, FileXML, ModelParams, grab_file_ctx, set_error


class AgentContext(TypedDict):
    user_prompt: str
    backend_files: NotRequired[dict[str, str]]
    frontend_files: NotRequired[dict[str, str]]
    bfs_definitions: NotRequired[logic.Node[NodeData]]
    bfs_handlers: NotRequired[logic.Node[NodeData]]
    bfs_backend_index: NotRequired[logic.Node[NodeData]]
    bfs_frontend: NotRequired[logic.Node[NodeData]]
    checkpoint: NotRequired[logic.Node[NodeData]]
    error: NotRequired[Exception]


async def eval_backend(ctx: AgentContext) -> bool:
    assert "bfs_definitions" in ctx, "bfs_definitions must be provided"
    solution: logic.Node[NodeData] | None = None
    children = [n for n in ctx["bfs_definitions"].get_all_children() if n.is_leaf]
    for n in children:
        assert len(n.data["messages"]) == 1, "node must have single completion message"
        content: list[ContentBlockParam] = []
        workspace = n.data["workspace"]
        for block in n.data["messages"][0]["content"]:
            if isinstance(block, TextBlock):
                for file in FileXML.from_string(block.text):
                    try:
                        workspace.write_file(file.path, file.content)
                        n.data["files"].update({file.path: file.content})
                    except PermissionError as e:
                        content.append({"type": "text", "text": str(e)})
        feedback = workspace.exec(["bun", "run", "tsc", "--noEmit"])
        if await feedback.exit_code() != 0:
            error = await feedback.stdout()
            content.append({"type": "text", "text": f"Error running tsc: {error}"})
        feedback = workspace.exec_with_pg(["bun", "run", "drizzle-kit", "push", "--force"])
        error = await feedback.stderr()
        if error or await feedback.exit_code() != 0:
            content.append({"type": "text", "text": f"Error running drizzle-kit push: {error}"})
        if content:
            n.data["messages"].append(MessageParam(role="user", content=content))
            continue
        solution = n
    if solution is None:
        return False
    ctx["backend_files"] = solution.data["files"]
    ctx["checkpoint"] = solution
    return True


async def eval_backend_handlers(ctx: AgentContext) -> bool:
    assert "bfs_handlers" in ctx, "bfs_handlers must be provided"

    expect_files = []
    for n in filter(lambda path: path.startswith("src/handlers"), ctx["backend_files"].keys()):
        name, ext = os.path.splitext(os.path.basename(n))
        expect_files.append(f"src/tests/{name}.test.ts")

    solution: logic.Node[NodeData] | None = None
    children = [n for n in ctx["bfs_handlers"].get_all_children() if n.is_leaf]
    for n in children:
        assert len(n.data["messages"]) == 1, "node must have single completion message"
        content: list[ContentBlockParam] = []
        workspace = n.data["workspace"]
        for block in n.data["messages"][0]["content"]:
            if isinstance(block, TextBlock):
                for file in FileXML.from_string(block.text):
                    try:
                        workspace.write_file(file.path, file.content)
                        n.data["files"].update({file.path: file.content})
                    except PermissionError as e:
                        content.append({"type": "text", "text": str(e)})
        feedback = workspace.exec(["bun", "run", "tsc", "--noEmit"])
        if await feedback.exit_code() != 0:
            error = await feedback.stdout()
            content.append({"type": "text", "text": f"Error running tsc: {error}"})
        missing_tests = [path for path in expect_files if path not in n.data["files"]]
        if missing_tests:
            content.append({"type": "text", "text": f"Missing test files: {missing_tests}"})
        feedback = workspace.exec_with_pg(["bun", "test"])
        if await feedback.exit_code() != 0:
            error = await feedback.stderr()
            content.append({"type": "text", "text": f"Error running tests: {error}"})
        if content:
            n.data["messages"].append(MessageParam(role="user", content=content))
            continue
        solution = n
    if solution is None:
        return False
    ctx["backend_files"].update(solution.data["files"])
    ctx["checkpoint"] = solution
    return True


async def eval_backend_index(ctx: AgentContext) -> bool:
    assert "bfs_backend_index" in ctx, "bfs_backend_index must be provided"
    solution: logic.Node[NodeData] | None = None
    children = [n for n in ctx["bfs_backend_index"].get_all_children() if n.is_leaf]
    for n in children:
        assert len(n.data["messages"]) == 1, "node must have single completion message"
        content: list[ContentBlockParam] = []
        workspace = n.data["workspace"]
        for block in n.data["messages"][0]["content"]:
            if isinstance(block, TextBlock):
                for file in FileXML.from_string(block.text):
                    try:
                        workspace.write_file(file.path, file.content)
                        n.data["files"].update({file.path: file.content})
                    except PermissionError as e:
                        content.append({"type": "text", "text": str(e)})
        feedback = workspace.exec(["bun", "run", "tsc", "--noEmit"])
        if await feedback.exit_code() != 0:
            error = await feedback.stdout()
            content.append({"type": "text", "text": f"Error running tsc: {error}"})
        if content:
            n.data["messages"].append(MessageParam(role="user", content=content))
            continue
        solution = n
    if solution is None:
        return False
    ctx["backend_files"].update(solution.data["files"])
    ctx["checkpoint"] = solution
    return True

# FSM logic and prompts

BACKEND_START_PROMPT = f"""
- Define all types using zod in a single file src/schema.ts
- Always define schema and corresponding type using z.infer<typeof typeSchemaName>
Example:
{playbooks.BASE_TYPESCRIPT_SCHEMA}

- Define all database tables using drizzle-orm in src/db/schema.ts
Example:
{playbooks.BASE_DRIZZLE_SCHEMA}

- For each handler write its declaration in corresponding file in src/handlers/
Example:
{playbooks.BASE_HANDLER_DECLARATION}

Key project files:
%(project_context)s

Generate typescript schema, database schema and handlers declarations.
Return code within <file path="src/handlers/handler_name.ts">...</file> tags.
On errors, modify only relevant files and return code within <file path="src/handlers/handler_name.ts">...</file> tags.

Task:
%(user_prompt)s
""".strip()


BACKEND_HANDLERS_PROMPT = f"""
- For each handler write small meaningful tests in src/tests/
- Write implementations for all handlers in src/handlers/
- Avoid modifying tests unless it is obviously incorrent

Example:
{playbooks.BASE_HANDLER_TEST}

Key project files:
%(project_context)s

Write tests and implementations for all handlers.
Return code within <file path="src/tests/handler_name.test.ts">...</file> tags.
On errors, modify only relevant files and return code within <file path="src/tests/handler_name.test.ts">...</file> tags.
""".strip()


BACKEND_INDEX_PROMPT = f"""
- Generate root TRPC index file in src/index.ts
Relevant parts to modify:
- Imports of handlers and schema types
- Registering TRPC routes
...
import {{ myHandlerInputSchema }} from './schema';
import {{ myHandler }} from './handlers/my_handler';
...
const appRouter = router({{
  myHandler: publicProcedure
    .input(myHandlerInputSchema)
    .query(({{ input }}) => myHandler(input)),
}});
...

- Rest should be repeated verbatim fron the example
Example:
{playbooks.BASE_SERVER_INDEX}

Key project files:
%(project_context)s

Generate ONLY root TRPC index file. Return code within <file path="src/index.ts">...</file> tags.
On errors, modify only index files and return code within <file path="src/index.ts">...</file> tags.
""".strip()


class FSMEvent(str, enum.Enum):
    PROMPT = "prompt"
    CONFIRM = "confirm"
    MAKE_HANDLERS = "make_handlers"
    MAKE_INDEX = "make_index"


class FSMState(str, enum.Enum):
    BACKEND_DRAFT_GEN = "backend_draft_gen"
    BACKEND_DRAFT_EVAL = "backend_draft_eval"
    BACKEND_DRAFT_DONE = "backend_draft_done"
    BACKEND_HANDLERS_GEN = "backend_handlers_gen"
    BACKEND_HANDLERS_EVAL = "backend_handlers_eval"
    BACKEND_HANDLERS_DONE = "backend_handlers_done"
    BACKEND_INDEX_GEN = "backend_index_gen"
    BACKEND_INDEX_EVAL = "backend_index_eval"
    BACKEND_INDEX_DONE = "backend_index_done"
    FRONTEND_DRAFT_GEN = "frontend_draft_gen"
    FRONTEND_DRAFT_EVAL = "frontend_draft_eval"
    FRONTEND_DRAFT_DONE = "frontend_draft_done"
    FAILED = "failed"


async def make_fsm_states(m_client: AsyncAnthropicBedrock, model_params: ModelParams, beam_width: int = 3) -> statemachine.State[AgentContext]:
    workspace = await Workspace.create(
        base_image="oven/bun:1.2.5-alpine",
        context=dag.host().directory("./prefabs/trpc_fullstack/server", exclude=["node_modules"]),
        setup_cmd=[["bun", "install"]],
    )
    actor_bfs_no_tools = BFSExpandActor(m_client, model_params, beam_width=beam_width)

    async def root_entry_draft_fn(ctx: AgentContext):
        if "bfs_definitions" in ctx:
            return
        draft_workspace = workspace.clone().permissions([], ["src/schema.ts", "src/db/schema.ts", "src/handlers/"])

        project_context = await grab_file_ctx(
            workspace=draft_workspace,
            files=["src/db/index.ts", "package.json"],
        )
        project_context = "\n".join([
            project_context,
            "DATABASE_URL=postgres://postgres:postgres@postgres:5432/postgres",
            f"Allowed paths and directories: {workspace.allowed}",
        ])
        message = MessageParam(
            role="user",
            content=[TextBlock(
                type="text",
                text=BACKEND_START_PROMPT % {
                    "project_context": project_context,
                    "user_prompt": ctx["user_prompt"],
                }
            )]
        )
        root = logic.Node[NodeData](
            data={"workspace": draft_workspace, "files": {}, "messages": [message]},
        )
        ctx["bfs_definitions"] = root
    
    async def root_entry_handlers_fn(ctx: AgentContext):
        if "bfs_handlers" in ctx:
            return
        handlers_workspace = workspace.clone().permissions([], [])
        for path, content in ctx["backend_files"].items():
            handlers_workspace.write_file(path, content)
        handlers_workspace.permissions([], ["src/tests/", "src/handlers/"])

        project_context = await grab_file_ctx(
            workspace=handlers_workspace,
            files=["src/helpers/index.ts"] + list(ctx["backend_files"].keys()),
        )
        project_context = "\n".join([
            project_context,
            f"Allowed paths and directories: {handlers_workspace.allowed}",
        ])
        message = MessageParam(
            role="user",
            content=[TextBlock(
                type="text",
                text=BACKEND_HANDLERS_PROMPT % {
                    "project_context": project_context,
                }
            )]
        )
        root = logic.Node[NodeData](
            data={"workspace": handlers_workspace, "files": {}, "messages": [message]},
        )
        ctx["bfs_handlers"] = root
    
    async def root_entry_backend_index(ctx: AgentContext):
        if "bfs_backend_index" in ctx:
            return
        index_workspace = workspace.clone().permissions([], [])
        for path, content in ctx["backend_files"].items():
            index_workspace.write_file(path, content)
        index_workspace.permissions([], ["src/index.ts"])

        handler_files = [f for f in ctx["backend_files"].keys() if f.startswith("src/handlers/")]
        project_context = await grab_file_ctx(
            workspace=index_workspace,
            files=["src/schema.ts"] + handler_files,
        )
        project_context = "\n".join([
            project_context,
            f"Allowed paths and directories: {index_workspace.allowed}",
        ])
        message = MessageParam(
            role="user",
            content=[TextBlock(
                type="text",
                text=BACKEND_INDEX_PROMPT % {
                    "project_context": project_context,
                }
            )]
        )
        root = logic.Node[NodeData](
            data={
                "workspace": index_workspace,
                "files": {},
                "messages": [message],
            },
        )
        ctx["bfs_backend_index"] = root

    m_states: statemachine.State[AgentContext] = {
        "on": {
            FSMEvent.PROMPT: FSMState.BACKEND_DRAFT_GEN,
            FSMEvent.MAKE_HANDLERS: FSMState.BACKEND_HANDLERS_GEN,
            FSMEvent.MAKE_INDEX: FSMState.BACKEND_INDEX_GEN,
        },
        "states": {
            FSMState.BACKEND_DRAFT_GEN: {
                "entry": [root_entry_draft_fn],
                "invoke": {
                    "src": actor_bfs_no_tools,
                    "input_fn": lambda ctx: (ctx["bfs_definitions"],),
                    "on_done": {"target": FSMState.BACKEND_DRAFT_EVAL},
                    "on_error": {
                        "target": FSMState.FAILED,
                        "actions": [set_error],
                    }
                }
            },
            FSMState.BACKEND_DRAFT_EVAL: {
                "always": [
                    {"target": FSMState.BACKEND_DRAFT_DONE, "guard": eval_backend},
                    {"target": FSMState.BACKEND_DRAFT_GEN},
                ]
            },
            FSMState.BACKEND_DRAFT_DONE: {
                "on": {
                    FSMEvent.CONFIRM: FSMState.BACKEND_HANDLERS_GEN,
                }
            },
            FSMState.BACKEND_HANDLERS_GEN: {
                "entry": [root_entry_handlers_fn],
                "invoke": {
                    "src": actor_bfs_no_tools,
                    "input_fn": lambda ctx: (ctx["bfs_handlers"],),
                    "on_done": {"target": FSMState.BACKEND_HANDLERS_EVAL},
                    "on_error": {
                        "target": FSMState.FAILED,
                        "actions": [set_error],
                    }
                }
            },
            FSMState.BACKEND_HANDLERS_EVAL: {
                "always": [
                    {"target": FSMState.BACKEND_HANDLERS_DONE, "guard": eval_backend_handlers},
                    {"target": FSMState.BACKEND_HANDLERS_GEN},
                ]
            },
            FSMState.BACKEND_HANDLERS_DONE: {
                "on": {
                    FSMEvent.CONFIRM: FSMState.BACKEND_INDEX_GEN,
                }
            },
            FSMState.BACKEND_INDEX_GEN: {
                "entry": [root_entry_backend_index],
                "invoke": {
                    "src": actor_bfs_no_tools,
                    "input_fn": lambda ctx: (ctx["bfs_backend_index"],),
                    "on_done": {"target": FSMState.BACKEND_INDEX_EVAL},
                    "on_error": {
                        "target": FSMState.FAILED,
                        "actions": [set_error],
                    }
                }
            },
            FSMState.BACKEND_INDEX_EVAL: {
                "always": [
                    {"target": FSMState.BACKEND_INDEX_DONE, "guard": eval_backend_index},
                    {"target": FSMState.BACKEND_INDEX_GEN},
                ]
            },
            FSMState.BACKEND_INDEX_DONE: {},
            FSMState.FAILED: {},
        }
    }
    return m_states