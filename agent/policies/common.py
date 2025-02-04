from typing import Optional, Self
from abc import ABC, abstractmethod
from contextlib import contextmanager
import concurrent.futures
from langfuse.decorators import langfuse_context, observe


class Node[T]:
    data: T
    parent: Optional[Self]
    children: list[Self]
    depth: int

    def __init__(self, data: T, parent: Optional[Self] = None):
        self.data = data
        self.parent = parent
        self.children = []
        self.depth = parent.depth + 1 if parent else 0

    @property
    def is_terminal(self) -> bool:
        return not self.children
    
    def get_trajectory(self) -> list[Self]:
        trajectory = []
        node: Self | None = self
        while node:
            trajectory.append(node)
            node = node.parent
        return trajectory[::-1]
    
    def _get_all_children(self) -> list[Self]:
        all_nodes, stack = [], [self]
        while stack:
            node = stack.pop()
            all_nodes.extend(node.children)
            stack.extend(node.children)
        return all_nodes


class TaskNode[T, U](ABC, Node[T]):
    @property
    @abstractmethod
    def run_args(self) -> U:
        ...

    @staticmethod
    @abstractmethod
    def run(input: U, *args, **kwargs) -> T:
        ...

    @property
    @abstractmethod
    def is_successful(self) -> bool:
        ...

    @property
    def is_expandable(self) -> bool:
        """By default if a node did not succeed, we can expand further."""
        return not self.is_successful  
    
    @property
    def score(self) -> float:
        """Defaults to binary reward 1.0 for success, 0.0 for failure."""
        return 1 if self.is_successful else 0
    
    def best_solution(self) -> Self:
        all_nodes = [self] + self._get_all_children()
        return max(all_nodes, key=lambda x: int(x.is_terminal) * x.score)

    @staticmethod
    @contextmanager
    def platform[**P](*args: P.args, **kwargs: P.kwargs):
        """Context manager for setting up globally accessible resources for workers."""
        try:
            yield
        finally:
            pass


@observe(capture_input=False, capture_output=False)  
def bfs[T: TaskNode](
    root: T,
    max_depth: int = 3,
    branch_factor: int = 3,
    max_workers: int = 5,
) -> T:
    trace_id = langfuse_context.get_current_trace_id()
    observation_id = langfuse_context.get_current_observation_id()
    while True:
        if root.best_solution().is_successful:
            break
        candidates: list[T] = []
        for node in [root] + root._get_all_children():
            if node.is_terminal and node.depth < max_depth and node.is_expandable:
                candidates.append(node)
        if not candidates:
            break
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_node: dict[concurrent.futures.Future, T] = {}
            for node in candidates:
                args = node.run_args
                for _ in range(branch_factor):
                    future_to_node[executor.submit(
                        node.run,
                        args,
                        langfuse_parent_trace_id=trace_id,
                        langfuse_parent_observation_id=observation_id,
                    )] = node
            for future in concurrent.futures.as_completed(future_to_node):
                node, result = future_to_node[future], future.result()
                node.children.append(type(node)(result, parent=node))
    return root.best_solution()
