from typing import Callable, Protocol, Self
import uuid
import concurrent.futures
from anthropic.types import MessageParam


class Node[T]:
    _id: str
    data: T
    parent: Self | None
    children: list[Self]

    def __init__(self, data: T, parent: Self | None = None, id: str | None = None):
        self._id = id if id else uuid.uuid4().hex
        self.data = data
        self.parent = parent
        self.children = []

    @property
    def is_leaf(self) -> bool:
        return not self.children
    
    @property
    def depth(self) -> int:
        return self.parent.depth + 1 if self.parent else 0
    
    def get_trajectory(self) -> list[Self]:
        stack = [self]
        while stack[-1].parent:
            stack.append(stack[-1].parent)
        return stack[::-1]
    
    def get_all_children(self) -> list[Self]:
        children, stack = [], [self]
        while stack:
            node = stack.pop()
            children.append(node)
            stack.extend(node.children)
        return children


class Scorable(Protocol):
    @property
    def score(self) -> float: ...

    @property
    def is_done(self) -> bool: ...


def best_solution[T: Scorable](root: Node[T]) -> Node[T] | None:
    return max(root.get_all_children(), key=lambda node: node.data.score, default=None)


def bfs[T: Scorable](
    root: Node[T],
    expand_fn: Callable[[Node[T]], Node[T]],
    max_depth: int = 5,
    max_width: int = 2,
    max_workers: int = 5,
) -> Node[T] | None:
    def select_fn(node: Node[T]) -> bool:
        return node.is_leaf and node.depth < max_depth

    while not ((best := best_solution(root)) and best.data.is_done):
        batch = [n for n in [root] + root.get_all_children() if select_fn(n)]
        if not batch:
            break
        with concurrent.futures.ThreadPoolExecutor(max_workers) as executor:
            future_to_node: dict[concurrent.futures.Future[Node[T]], Node[T]] = {}
            for node in batch:
                for _ in range(max_width):
                    future_to_node[executor.submit(expand_fn, node)] = node
            for future in concurrent.futures.as_completed(future_to_node):
                node, new_node = future_to_node[future], future.result()
                node.children.append(new_node)
    return best_solution(root)


def dfs[T: Scorable](
    root: Node[T],
    expand_fn: Callable[[Node[T]], Node[T]],
    max_depth: int = 5,
    max_width: int = 2,
    max_budget: int | None = None,
) -> Node[T] | None:
    stack, cur_budget = [root], 0
    max_nodes = max_budget if max_budget else sum([max_width ** i for i in range(max_depth)])
    while stack and cur_budget < max_nodes and not ((best := best_solution(root)) and best.data.is_done):
        cur_node = stack[-1]
        if cur_node.depth >= max_depth or len(cur_node.children) >= max_width:
            stack.pop()
            continue
        new_node = expand_fn(cur_node)
        cur_node.children.append(new_node)
        stack.append(new_node)
        cur_budget = cur_budget + 1
    return best_solution(root)


def dfs_rewind[T: Scorable](
    root: Node[T],
    expand_fn: Callable[[Node[T]], Node[T]],
    max_depth: int = 5,
    max_width: int = 2,
    max_budget: int | None = None,
) -> Node[T] | None:
    stack, cur_budget = [root], 0
    max_nodes = max_budget if max_budget else sum([max_width ** i for i in range(max_depth)])
    while stack and cur_budget < max_nodes and not ((best := best_solution(root)) and best.data.is_done):
        head_node = stack.pop(0)
        if head_node.depth >= max_depth or len(head_node.children) >= max_width:
            stack.extend(head_node.children)
            continue
        stack.append(head_node) # shuffle back to uniformly explore
        cur_node = head_node
        while cur_node.depth < max_depth and len(cur_node.children) < max_width and not cur_node.data.is_done:
            new_node = expand_fn(cur_node)
            cur_node.children.append(new_node)
            cur_node, cur_budget = new_node, cur_budget + 1
    return best_solution(root)


# Agent specific implementations


class AgentMachine[T](Scorable):
    @property
    def next_message(self) -> MessageParam | None: ...

    def on_message(self, context: T, message: MessageParam) -> "AgentMachine[T]": ...


class AgentState[T](AgentMachine[T]):
    inner: AgentMachine[T]
    event: MessageParam | None

    def __init__(self, inner: AgentMachine[T], event: MessageParam | None):
        self.inner = inner
        self.event = event

    @property
    def score(self) -> float:
        return self.inner.score
    
    @property
    def is_done(self) -> bool:
        return self.inner.is_done

    @property
    def next_message(self) -> MessageParam | None:
        return self.inner.next_message
    
    def on_message(self, context: T, message: MessageParam) -> "AgentState[T]":
        return type(self)(self.inner.on_message(context, message), message)
    
    @property
    def thread(self) -> list[MessageParam]:
        return [m for m in (self.event, self.inner.next_message) if m]
