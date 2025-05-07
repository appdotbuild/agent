import os
import re
import anyio
import jinja2
import logging
from core.base_node import Node
from core.workspace import Workspace
from core.actors import BaseData, BaseActor, LLMActor
from llm.common import AsyncLLM, Message, TextRaw, Tool, ToolUse, ToolUseResult

logger = logging.getLogger(__name__)


class SillyActor(BaseActor, LLMActor):
    root: Node[BaseData] | None = None

    def __init__(self, llm: AsyncLLM, workspace: Workspace, beam_width: int = 1, max_depth: int = 10):
        self.llm = llm
        self.workspace = workspace
        self.beam_width = beam_width
        self.max_depth = max_depth
        self.root = None
        logger.info(f"Initialized {self.__class__.__name__} with beam_width={beam_width}, max_depth={max_depth}")

    async def search(self, node: Node[BaseData] | None) -> Node[BaseData] | None:
        if node is None:
            raise RuntimeError("Node cannot be None")
        logger.info(f"Starting search from node at depth {node.depth}")
        solution: Node[BaseData] | None = None
        iteration = 0

        while solution is None:
            iteration += 1
            candidates = self.select(node)
            if not candidates:
                logger.info("No candidates to evaluate, search terminated")
                break

            logger.info(f"Iteration {iteration}: Running LLM on {len(candidates)} candidates")
            nodes = await self.run_llm(candidates, tools=self.tools, max_tokens=8192)#, force_tool_use=True)
            logger.info(f"Received {len(nodes)} nodes from LLM")

            for i, new_node in enumerate(nodes):
                logger.info(f"Evaluating node {i+1}/{len(nodes)}")
                if await self.eval_node(new_node):
                    logger.info(f"Found solution at depth {new_node.depth}")
                    solution = new_node
                    break

        return solution

    def select(self, node: Node[BaseData]) -> list[Node[BaseData]]:
        if node.is_leaf:
            logger.info(f"Selecting root node {self.beam_width} times (beam search)")
            return [node] * self.beam_width

        candidates = [n for n in node.get_all_children() if n.is_leaf and n.depth <= self.max_depth]
        logger.info(f"Selected {len(candidates)} leaf nodes for evaluation")
        return candidates

    @classmethod
    def file_as_xml(cls, file_path: str, content: str) -> str:
        return f"\n<file path=\"{file_path}\">\n{content.strip()}\n</file>\n"

    @property
    def tools(self) -> list[Tool]:
        return [
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
            {
                "name": "write_file",
                "description": "Write a file",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                }
            },
            {
                "name": "delete_file",
                "description": "Delete a file",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                }
            },
            {
                "name": "mark_complete",
                "description": "Call to run type checks and / or tell the task is completed",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "is_complete": {
                            "type": "boolean",
                            "description": "True if task is completed false if just running type checks"
                        }
                    },
                    "required": ["is_complete"],
                }
            }
        ]

    async def dump(self) -> object:
        if self.root is None:
            return []
        return await self.dump_node(self.root)

    async def load(self, data: object):
        if not isinstance(data, list):
            raise ValueError(f"Expected list got {type(data)}")
        if not data:
            return
        self.root = await self.load_node(data)

    async def run_tools(self, node: Node[BaseData]) -> tuple[list[ToolUseResult], bool]:
        result, is_complete = [], False
        for block in node.data.head().content:
            if not isinstance(block, ToolUse):
                continue
            try:
                match block.name:
                    case "read_file":
                        tool_content = await node.data.workspace.read_file(block.input["path"]) # pyright: ignore[reportIndexIssue]
                        result.append(ToolUseResult.from_tool_use(block, tool_content))
                    case "write_file":
                        node.data.workspace.write_file(block.input["path"], block.input["content"]) # pyright: ignore[reportIndexIssue]
                        result.append(ToolUseResult.from_tool_use(block, "success"))
                        node.data.files[block.input["path"]] = block.input["content"] # pyright: ignore[reportIndexIssue]
                    case "delete_file":
                        result.append(ToolUseResult.from_tool_use(block, "success"))
                        node.data.workspace.rm(block.input["path"]) # pyright: ignore[reportIndexIssue]
                    case "mark_complete":
                        check_err = await self.run_checks(node)
                        result.append(ToolUseResult.from_tool_use(block, check_err or "success"))
                        is_complete = block.input["is_complete"] and check_err is None # pyright: ignore[reportIndexIssue]
                    case unknown:
                        raise ValueError(f"Unknown tool: {unknown}")
            except FileNotFoundError as e:
                result.append(ToolUseResult.from_tool_use(block, str(e), is_error=True))
            except PermissionError as e:
                result.append(ToolUseResult.from_tool_use(block, str(e), is_error=True))
            except ValueError as e:
                result.append(ToolUseResult.from_tool_use(block, str(e), is_error=True))
        return result, is_complete

    async def eval_node(self, node: Node[BaseData]) -> bool:
        tool_calls, is_completed = await self.run_tools(node)
        if tool_calls:
            node.data.messages.append(Message(role="user", content=tool_calls))
        else:
            content = [TextRaw(text="Continue or mark completed.")]
            node.data.messages.append(Message(role="user", content=content))
        return is_completed

    async def run_checks(self, node: Node[BaseData]) -> str | None:
        ...


class EditActor(SillyActor):
    root: Node[BaseData] | None = None
    allowed: list[str] = []
    protected: list[str] = []
    injected: list[str] = []
    visible: list[str] = []

    def __init__(
        self,
        llm: AsyncLLM,
        workspace: Workspace,
        prompt_template: str,
        beam_width: int = 1,
        max_depth: int = 10,
        ws_allowed: list[str] = [],
        ws_protected: list[str] = [],
        ws_injected: list[str] = [],
        ws_visible: list[str] = [],
    ):
        super().__init__(llm, workspace, beam_width, max_depth)
        self.prompt_template = prompt_template
        self.allowed = ws_allowed
        self.protected = ws_protected
        self.injected = ws_injected
        self.visible = ws_visible

    async def execute(
        self,
        files: dict[str, str],
        user_prompt: str,
        edit_set: list[str] | None = None,
    ) -> Node[BaseData]:
        workspace = self.workspace.clone()
        for file_path, content in files.items():
            workspace.write_file(file_path, content)
        if edit_set:
            self.allowed = edit_set
            logger.info(f"Allowed files updated: {edit_set}")
        workspace.permissions(protected=self.protected, allowed=self.allowed)
        files_ctx: list[str] = [
            self.file_as_xml(file_path, content)
            for file_path, content in files.items()
        ]
        workspace_files_ctx: list[str] = []
        for file_path in self.injected:
            workspace_files_ctx.append(self.file_as_xml(file_path, await self.workspace.read_file(file_path)))
        workspace_visible_ctx: list[str] = []
        for name in self.visible:
            if name.endswith("/"):
                file_list = await workspace.ls(name)
                workspace_visible_ctx.extend([f"{name}{file}" for file in file_list])
            else:
                workspace_visible_ctx.append(name)
        jinja_env = jinja2.Environment()
        text = jinja_env.from_string(self.prompt_template).render(
            files_ctx=files_ctx,
            workspace_ctx=workspace_files_ctx,
            workspace_visible_ctx=workspace_visible_ctx,
            allowed=self.allowed,
            protected=self.protected,
            user_prompt=user_prompt,
        )
        message = Message(role="user", content=[TextRaw(text=text)])
        self.root = Node(BaseData(workspace, [message], {}))

        solution = await self.search(self.root)
        if solution is None:
            raise ValueError("No solution found")
        return solution

    async def run_checks(self, node: Node[BaseData]) -> str | None:
        errors: list[str] = []

        logger.info("Running server tsc compile")
        tsc_result = await node.data.workspace.exec(["bun", "run", "tsc", "--noEmit"], cwd="server")
        if tsc_result.exit_code != 0:
            errors.append(f"Error running tsc: {tsc_result.stdout}")

        logger.info("Running client tsc compile")
        tsc_result = await node.data.workspace.exec(["bun", "run", "tsc", "-p", "tsconfig.app.json", "--noEmit"], cwd="client")
        if tsc_result.exit_code != 0:
            errors.append(f"Error running tsc: {tsc_result.stdout}")

        if errors:
            return "\n".join(errors)

        logger.info("Running server tests")
        test_result = await node.data.workspace.exec_with_pg(["bun", "test"], cwd="server")
        if test_result.exit_code != 0:
            normalized = self.normalize_tests(test_result.stderr)
            errors.append(f"Error running tests: {normalized}")

        return "\n".join(errors) if errors else None

    @classmethod
    def normalize_tests(cls, stderr: str) -> str:
        pattern = re.compile(r"\[\d+(\.\d+)?ms\]")
        return pattern.sub("[DURATION]", stderr)

    async def dump(self) -> object:
        if self.root is None:
            return {}
        return {
            "root": await self.dump_node(self.root),
            "allowed": self.allowed,
            "protected": self.protected,
            "injected": self.injected,
            "visible": self.visible,
        }

    async def load(self, data: object):
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict got {type(data)}")
        if not data:
            return
        self.root = await self.load_node(data["root"])
        self.allowed = data.get("allowed", [])
        self.protected = data.get("protected", [])
        self.injected = data.get("injected", [])
        self.visible = data.get("visible", [])


class EditSetActor(SillyActor):
    root: Node[BaseData] | None = None

    def __init__(
        self,
        llm: AsyncLLM,
        workspace: Workspace,
        prompt_template: str,
        beam_width: int = 1,
        max_depth: int = 10,
    ):
        super().__init__(llm, workspace, beam_width, max_depth)
        self.prompt_template = prompt_template

    async def execute(self, files: dict[str, str], user_prompt: str) -> list[str]:
        workspace = self.workspace.clone()
        for file_path, content in files.items():
            workspace.write_file(file_path, content)
        files_ctx: list[str] = [
            self.file_as_xml(file_path, content)
            for file_path, content in files.items()
        ]
        jinja_env = jinja2.Environment()
        text = jinja_env.from_string(self.prompt_template).render(
            files_ctx=files_ctx,
            user_prompt=user_prompt,
        )
        logger.info(f"Generated prompt: {text}")
        message = Message(role="user", content=[TextRaw(text=text)])
        self.root = Node(BaseData(workspace, [message], {}))

        solution = await self.search(self.root)
        if solution is None:
            raise ValueError("No solution found")
        for block in solution.data.messages[0].content:
            match block:
                case ToolUse(name="mark_changeset", input=args):
                    return args["files"] # pyright: ignore[reportIndexIssue]
                case _:
                    continue
        raise ValueError("No files marked for edit")

    async def run_tools(self, node: Node[BaseData]) -> tuple[list[ToolUseResult], bool]:
        result, is_complete = [], False
        for block in node.data.head().content:
            if not isinstance(block, ToolUse):
                continue
            try:
                match block.name:
                    case "write_file":
                        node.data.workspace.write_file(block.input["path"], block.input["content"]) # pyright: ignore[reportIndexIssue]
                        result.append(ToolUseResult.from_tool_use(block, "success"))
                        node.data.files[block.input["path"]] = block.input["content"] # pyright: ignore[reportIndexIssue]
                    case "run_checks":
                        check_err = await self.run_checks(node)
                        result.append(ToolUseResult.from_tool_use(block, check_err or "success"))
                    case "mark_changeset":
                        result.append(ToolUseResult.from_tool_use(block, "success"))
                        is_complete = True
                    case unknown:
                        raise ValueError(f"Unknown tool: {unknown}")
            except FileNotFoundError as e:
                result.append(ToolUseResult.from_tool_use(block, str(e), is_error=True))
            except PermissionError as e:
                result.append(ToolUseResult.from_tool_use(block, str(e), is_error=True))
            except ValueError as e:
                result.append(ToolUseResult.from_tool_use(block, str(e), is_error=True))
        return result, is_complete

    async def run_checks(self, node: Node[BaseData]) -> str | None:
        errors: list[str] = []

        logger.info("Running server tsc compile")
        tsc_result = await node.data.workspace.exec(["bun", "run", "tsc", "--noEmit"], cwd="server")
        if tsc_result.exit_code != 0:
            errors.append(f"Error running tsc: {tsc_result.stdout}")

        logger.info("Running client tsc compile")
        tsc_result = await node.data.workspace.exec(["bun", "run", "tsc", "-p", "tsconfig.app.json", "--noEmit"], cwd="client")
        if tsc_result.exit_code != 0:
            errors.append(f"Error running tsc: {tsc_result.stdout}")

        return "\n".join(errors) if errors else None

    @property
    def tools(self) -> list[Tool]:
        return [
            {
                "name": "write_file",
                "description": "Write a file",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                }
            },
            {
                "name": "run_checks",
                "description": "Run compile checks to see if any other code is affected",
                "input_schema": {}
            },
            {
                "name": "mark_changeset",
                "description": "Mark files to create / edit / delete or run compile checks",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "files": {
                            "type": "array",
                            "items": {
                                "type": "string"
                            },
                            "description": "List of file paths related to the operation"
                        },
                    },
                    "required": ["files"],
                }
            }
        ]

    async def dump(self) -> object:
        if self.root is None:
            return []
        return await self.dump_node(self.root)

    async def load(self, data: object):
        if not isinstance(data, list):
            raise ValueError(f"Expected list got {type(data)}")
        if not data:
            return
        self.root = await self.load_node(data)


async def main(user_prompt="Add feature to create plain notes without status."):
    import json
    import dagger
    from llm.utils import get_llm_client
    from trpc_agent.playbooks import EDIT_SET_PROMPT, SILLY_PROMPT

    with open("./trpc_agent/todo_app_snapshot.json", "r") as f:
        files = json.load(f)

    async with dagger.connection(dagger.Config(log_output=open(os.devnull, "w"))):
        llm = get_llm_client(model_name="gemini-flash")

        workspace = await Workspace.create(
            base_image="oven/bun:1.2.5-alpine",
            context=dagger.dag.host().directory("./trpc_agent/template"),
            setup_cmd=[["bun", "install"]],
        )

        edit_set_actor = EditSetActor(
            llm,
            workspace.clone(),
            prompt_template=EDIT_SET_PROMPT,
        )

        edit_actor = EditActor(
            llm,
            workspace.clone(),
            SILLY_PROMPT,
            ws_allowed=[
                "server/src/schema.ts",
                "server/src/db/schema.ts",
                "server/src/handlers/",
                "server/src/tests/",
                "server/src/index.ts",
                "client/src/App.tsx",
                "client/src/components/",
                "client/src/App.css",
            ],
            ws_protected=[
                "server/src/db/index.ts",
                "client/src/utils/trpc.ts",
                "client/src/components/ui",
            ],
            ws_injected=[
                "client/src/utils/trpc.ts",
                "client/src/lib/utils.ts",
            ],
            ws_visible=["client/src/components/ui/"],
            max_depth=70,
        )

        edit_set = await edit_set_actor.execute(files, user_prompt)

        solution = await edit_actor.execute(files, user_prompt, edit_set)

        if solution:
            changeset = {}
            for node in solution.get_trajectory():
                changeset.update(node.data.files)
            for file_name, file_content in changeset.items():
                print(f"File: {file_name}")
                print(file_content)
        else:
            print("No solution found")

if __name__ == "__main__":
    anyio.run(main)
