from typing import TypedDict, NotRequired
import enum
from dagger import dag
import logic
import playbooks
import statemachine
from workspace import Workspace
from models.common import AsyncLLM, Message, TextRaw, Tool, ToolUse, ToolUseResult, ContentBlock
from shared_fsm import BFSExpandActor, ModelParams, NodeData, FileXML, grab_file_ctx, set_error, print_error


class AgentContext(TypedDict):
    user_prompt: str
    backend_files: dict[str, str]
    frontend_files: dict[str, str]
    bfs_frontend: NotRequired[logic.Node[NodeData]]
    checkpoint: NotRequired[logic.Node[NodeData]]
    error: NotRequired[Exception]


class FSMEvent(str, enum.Enum):
    PROMPT = "prompt"
    CONFIRM = "confirm"
    EJECT = "eject"


class FSMState(str, enum.Enum):
    GENERATING = "generating"
    EVALUATING = "evaluating"
    FAILED = "failed"
    SUCCEEDED = "succeeded"


async def eval_frontend(ctx: AgentContext) -> bool:
    assert "bfs_frontend" in ctx, "bfs_frontend must be provided"
    solution: logic.Node[NodeData] | None = None
    children = [n for n in ctx["bfs_frontend"].get_all_children() if n.is_leaf]
    for n in children:
        content: list[ContentBlock] = []
        workspace = n.data.workspace
        for block in n.data.head().content:
            if isinstance(block, TextRaw):
                for file in FileXML.from_string(block.text):
                    try:
                        workspace.write_file(file.path, file.content)
                        n.data.files.update({file.path: file.content})
                    except PermissionError as e:
                        content.append(TextRaw(str(e)))
            if isinstance(block, ToolUse):
                match block.name:
                    case "read_file":
                        try:
                            tool_content = await workspace.read_file(block.input["path"]) # pyright: ignore[reportIndexIssue]
                            content.append(ToolUseResult.from_tool_use(block, tool_content))
                        except FileNotFoundError as e:
                            content.append(ToolUseResult.from_tool_use(block, str(e), is_error=True))
                    case unknown:
                        content.append(ToolUseResult.from_tool_use(block, f"Unknown tool: {unknown}", is_error=True))
        feedback = workspace.exec(["bun", "tsc", "-p", "tsconfig.app.json", "--noEmit"])
        if await feedback.exit_code() != 0:
            error = await feedback.stdout()
            content.append(TextRaw(f"Error running tsc: {error}"))
        if content:
            n.data.messages.append(Message(role="user", content=content))
            continue
        solution = n
    if solution is None:
        return False
    ctx["frontend_files"].update(solution.data.files)
    ctx["checkpoint"] = solution
    return True


WS_TOOLS: list[Tool] = [
    {
        "name": "read_file",
        "description": "Read a file",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
        }
    },
]


FRONTEND_PROMPT = f"""
- Generate react frontend application using radix-ui components.
- Backend communication is done via TRPC.

Example:
{playbooks.BASE_APP_TSX}

Key project files:
%(project_context)s

Return code within <file path="src/components/component_name.tsx">...</file> tags.
On errors, modify only relevant files and return code within <file path="...">...</file> tags.

Task:
%(user_prompt)s
""".strip()


async def make_fsm_states(m_client: AsyncLLM, model_params: ModelParams, beam_width: int = 3):
    workspace = await Workspace.create(
        base_image="oven/bun:1.2.5-alpine",
        context=dag.host().directory("./prefabs/trpc_fullstack"),
        setup_cmd=[["bun", "install"]],
    )
    workspace.ctr = workspace.ctr.with_workdir("/app/client")
    actor_bfs_with_tools = BFSExpandActor(m_client, model_params, beam_width=beam_width)

    async def root_entry_fn(ctx: AgentContext):
        if "bfs_frontend" in ctx:
            return
        
        frontend_workspace = workspace.clone()
        for path, content in ctx["frontend_files"].items():
            frontend_workspace.write_file(path, content)
        for path, content in ctx["backend_files"].items():
            frontend_workspace.write_file("/app/server/" + path, content)
        frontend_workspace.permissions(["src/components/ui"], ["src/App.tsx", "src/components/", "src/App.css"])

        project_context = await grab_file_ctx(
            workspace=frontend_workspace,
            files=["/app/server/src/schema.ts", "/app/server/src/index.ts", "src/utils/trpc.ts"] + list(ctx["frontend_files"].keys()),
        )
        ui_files = await frontend_workspace.ls("src/components/ui")
        project_context = "\n".join([
            project_context,
            f"UI components in src/components/ui: {ui_files}",
            f"Allowed paths and directories: {frontend_workspace.allowed}",
            f"Protected paths and directories: {frontend_workspace.protected}",
        ])
        message = Message(
            role="user",
            content=[TextRaw(
                FRONTEND_PROMPT % {
                    "project_context": project_context,
                    "user_prompt": ctx["user_prompt"],
                }
            )]
        )
        ctx["bfs_frontend"] = logic.Node(NodeData(frontend_workspace, [message]))

    m_states: statemachine.State[AgentContext] = {
        "on": {
            FSMEvent.PROMPT: FSMState.GENERATING,
        },
        "states": {
            FSMState.GENERATING: {
                "entry": [root_entry_fn],
                "invoke": {
                    "src": actor_bfs_with_tools,
                    "input_fn": lambda ctx: (ctx["bfs_frontend"],), # pyright: ignore[reportTypedDictNotRequiredAccess]
                    "on_done": {"target": FSMState.EVALUATING},
                    "on_error": {
                        "target": FSMState.FAILED,
                        "actions": [set_error],
                    }
                }
            },
            FSMState.EVALUATING: {
                "always": [
                    {"target": FSMState.SUCCEEDED, "guard": eval_frontend},
                    {"target": FSMState.GENERATING},
                ]
            },
            FSMState.SUCCEEDED: {},
            FSMState.FAILED: {"entry": [print_error]},
        }
    }
    return m_states
