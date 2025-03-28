from typing import TypedDict, NotRequired
import dataclasses
import re
import anyio
from anyio.streams.memory import MemoryObjectSendStream
import logic
from workspace import Workspace
from models.common import AsyncLLM, Message, Tool, TextRaw, ToolUse, ThinkingBlock


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
    tools: NotRequired[list[Tool]]


@dataclasses.dataclass
class NodeData:
    workspace: Workspace
    messages: list[Message]
    files: dict[str, str] = dataclasses.field(default_factory=dict)

    def head(self) -> Message:
        if (num_messages := len(self.messages)) != 1:
            raise ValueError(f"Expected 1 got {num_messages} messages: {self.messages}")
        if self.messages[0].role != "assistant":
            raise ValueError(f"Expected assistant role in message: {self.messages}")
        return self.messages[0]


class BFSExpandActor:
    m_client: AsyncLLM
    model_params: ModelParams

    def __init__(self, m_client: AsyncLLM, model_params: ModelParams, beam_width: int = 5):
        self.m_client = m_client
        self.model_params = model_params
        self.beam_width = beam_width
    
    async def execute(self, root: logic.Node[NodeData]) -> logic.Node[NodeData]:
        async def task_fn(node: logic.Node[NodeData], tx: MemoryObjectSendStream[logic.Node[NodeData]]):
            history = [m for n in node.get_trajectory() for m in n.data.messages]
            new_node = logic.Node[NodeData](
                data=NodeData(
                    workspace=node.data.workspace.clone(),
                    messages=[await self.completion(history)],
                    files=node.data.files.copy(),
                ),
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
                    new_node.parent.children.append(new_node) # pyright: ignore[reportOptionalMemberAccess]
        return root

    async def completion(self, messages: list[Message]) -> Message:
        assert len(messages) > 0, "messages must not be empty"
        assert messages[-1].role == "user", "last message must be from user"
        content: list[TextRaw | ToolUse | ThinkingBlock] = []
        while True:
            payload = messages + [Message(role="assistant", content=content)] if content else messages
            completion = await self.m_client.completion(messages=payload, **self.model_params)
            content.extend(completion.content)
            if completion.stop_reason != "max_tokens":
                break
        return Message(role="assistant", content=self._merge_text(content))
    
    @staticmethod
    def _merge_text(content: list[TextRaw | ToolUse | ThinkingBlock]) -> list[TextRaw | ToolUse | ThinkingBlock]:
        text_blocks: list[TextRaw] = [block for block in content if isinstance(block, TextRaw)]
        other_blocks: list[ToolUse | ThinkingBlock] = [block for block in content if not isinstance(block, TextRaw)]
        return [TextRaw(" ".join(block.text for block in text_blocks))] + other_blocks


# minor helpers

async def grab_file_ctx(workspace: Workspace, files: list[str]) -> str:
    context = []
    for path in files:
        content = await workspace.read_file(path)
        context.append(f"<file path=\"{path}\">\n{content.strip()}\n</file>")
    return "\n\n".join(context)


class CtxWithError(TypedDict, total=False):
    error: Exception


async def set_error[T: CtxWithError](ctx: T, error: Exception):
    ctx["error"] = error


async def print_error[T: CtxWithError](ctx: T):
    print(ctx["error"])
