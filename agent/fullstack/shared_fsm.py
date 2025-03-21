from typing import Awaitable, Callable, TypedDict, NotRequired
import dataclasses
import re
import anyio
from anyio.streams.memory import MemoryObjectSendStream
from anthropic import AsyncAnthropic
from anthropic.types import ToolParam, ToolUseBlock, ToolResultBlockParam, MessageParam, ContentBlockParam
import logic
from workspace import Workspace


@dataclasses.dataclass
class FileXML:
    path: str
    content: str

    @staticmethod
    def from_string(content: str) -> list["FileXML"]:
        pattern = re.compile(r"<file path=\"([^\"]+)\">(.*?)</file>", re.DOTALL)
        files = pattern.findall(content)
        return [FileXML(path=f[0], content=f[1].strip()) for f in files]


class ModelParams(TypedDict):
    model: str
    max_tokens: int
    temperature: NotRequired[float]
    stop_sequences: NotRequired[list[str]]
    tools: NotRequired[list[ToolParam]]


class NodeData(TypedDict):
    workspace: Workspace
    files: dict[str, str]
    messages: list[MessageParam]


class WorkspaceTool(TypedDict):
    definition: ToolParam
    handler: Callable[[NodeData, ToolUseBlock], Awaitable[ToolResultBlockParam]]


class BFSExpandActor:
    m_client: AsyncAnthropic
    model_params: ModelParams

    def __init__(self, m_client: AsyncAnthropic, model_params: ModelParams, beam_width: int = 5):
        self.m_client = m_client
        self.model_params = model_params
        self.beam_width = beam_width
    
    async def execute(self, root: logic.Node[NodeData]) -> logic.Node[NodeData]:
        async def task_fn(node: logic.Node[NodeData], tx: MemoryObjectSendStream[logic.Node[NodeData]]):
            history = [m for n in node.get_trajectory() for m in n.data["messages"]]
            new_node = logic.Node[NodeData](
                data={
                    "workspace": node.data["workspace"].clone(),
                    "messages": [await self.completion(history)],
                    "files": node.data["files"].copy()
                },
                parent=node
            )
            async with tx:
                await tx.send(new_node)
        
        candidates = [root] * self.beam_width if root.is_leaf else [n for n in root.get_all_children() if n.is_leaf]
        tx, rx = anyio.create_memory_object_stream[logic.Node[NodeData]]()
        async with anyio.create_task_group() as tg:
            for n in candidates:
                tg.start_soon(task_fn, n, tx.clone())
            tx.close()
            async with rx:
                async for new_node in rx:
                    new_node.parent.children.append(new_node)
        return root

    async def completion(self, messages: list[MessageParam], tools: list[WorkspaceTool] | None = None) -> MessageParam:
        assert len(messages) > 0, "messages must not be empty"
        assert messages[-1]["role"] == "user", "last message must be from user"
        model_params = self.model_params.copy()
        if tools:
            model_params.update({"tools": [tool["definition"] for tool in tools]})
        content: list[ContentBlockParam] = []
        while True:
            payload = messages + [MessageParam(role="assistant", content=content)] if content else messages
            completion = await self.m_client.messages.create(messages=payload, **model_params)
            content.extend(completion.content)
            if (
                ("stop_sequences" in self.model_params and completion.stop_reason == "stop_sequence")
                or completion.stop_reason != "max_tokens"
            ):
                break
        return MessageParam(role="assistant", content=content)


# minor helpers

async def grab_file_ctx(workspace: Workspace, files: list[str]) -> str:
    context = []
    for path in files:
        content = await workspace.read_file(path)
        context.append(f"<file path=\"{path}\">\n{content.strip()}\n</file>")
    return "\n\n".join(context)


async def set_error(ctx: dict, error: Exception):
    ctx["error"] = error


async def print_error(ctx: dict):
    print(ctx["error"])
