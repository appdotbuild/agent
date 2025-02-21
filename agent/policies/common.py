from typing import Optional, Self
from abc import ABC, abstractmethod
from contextlib import contextmanager
import concurrent.futures
from langfuse.decorators import langfuse_context, observe


class PolicyException(Exception):
    def __init__(self, message: str):
        super().__init__(message)


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
    **kwargs,
) -> T:
    """Breadth-first search with parallelized expansion. KWARGS are passed to run method."""
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
                        **kwargs,
                        langfuse_parent_trace_id=trace_id,
                        langfuse_parent_observation_id=observation_id,
                    )] = node
            for future in concurrent.futures.as_completed(future_to_node):
                node, result = future_to_node[future], future.result()
                node.children.append(type(node)(result, parent=node))
    return root.best_solution()


@observe(capture_input=False, capture_output=False)
def dfs[T: TaskNode](
    root: T,
    max_depth: int = 5,
    max_width: int = 3,
    budget_lim: int | None = None,
    **kwargs,
) -> T:
    cur_node, budget_used = root, 0
    budget_lim = budget_lim or max_width ** max_depth
    while cur_node and budget_used < budget_lim:
        if cur_node.best_solution().is_successful:
            break
        if (
            cur_node.depth >= max_depth 
            or not cur_node.is_expandable 
            or len(cur_node.children) >= max_width
        ):
            cur_node = cur_node.parent
            continue
        data = cur_node.run(cur_node.run_args, **kwargs)
        new_node = type(cur_node)(data, parent=cur_node)
        cur_node.children.append(new_node)
        cur_node, budget_used = new_node, budget_used + 1
    return root.best_solution()
