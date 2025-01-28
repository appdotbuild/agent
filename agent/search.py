from typing import Optional, TypedDict

import concurrent.futures
from anthropic import AnthropicBedrock

from core import stages
from services import CompilerService
from compiler.core import CompileResult


class Node[T]:
    data: T
    score: float
    parent: Optional["Node[T]"]
    children: list["Node[T]"]
    depth: int

    def __init__(self, data: T, score, parent: Optional["Node[T]"] = None):
        self.data = data
        self.score = score
        self.parent = parent
        self.children = []
        self.depth = parent.depth + 1 if parent else 0

    @property
    def is_terminal(self) -> bool:
        return not self.children
    
    def get_trajectory(self) -> list["Node[T]"]:
        trajectory = []
        node = self
        while node:
            trajectory.append(node)
            node = node.parent
        return trajectory[::-1]
    
    def best_solution(self) -> "Node[T]":
        all_nodes = [self] + self._get_all_children()
        return max(all_nodes, key=lambda x: int(x.is_terminal) * x.score)
    
    def _get_all_children(self) -> list["Node[T]"]:
        all_nodes, stack = [], [self]
        while stack:
            node = stack.pop()
            all_nodes.extend(node.children)
            stack.extend(node.children)
        return all_nodes


class TypespecData(TypedDict):
    message: dict
    output: stages.typespec.TypespecOutput
    feedback: CompileResult


class DrizzleData(TypedDict):
    message: dict
    output: stages.drizzle.DrizzleOutput
    feedback: CompileResult


class SearchPolicy:
    client: AnthropicBedrock
    compiler: CompilerService

    def __init__(self, client: AnthropicBedrock, compiler: CompilerService):
        self.client = client
        self.compiler = compiler
        self._model = "anthropic.claude-3-5-sonnet-20241022-v2:0"

    @staticmethod
    def run_typespec(
        messages: list[dict],
        client: AnthropicBedrock,
        compiler: CompilerService,
        model: str,
    ) -> TypespecData:
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            messages=messages,
        )
        output = stages.typespec.parse_output(response.content[0].text)
        schema = "\n".join(['import "./helpers.js";', output["typespec_definitions"]])
        feedback = compiler.compile_typespec(schema)
        return {
            "message": {"role": "assistant", "content": response.content[0].text},
            "output": output,
            "feedback": feedback,
        }

    def bfs_typespec(
        self,
        init_message: dict,
        root: Node[TypespecData],
        max_depth: int = 3,
        branch_factor: int = 3,
        max_workers: int = 5,
    ) -> Node[TypespecData]:
        while True:
            if root.best_solution().score == 1:
                break
            
            candidates: list[Node[TypespecData]] = []
            for node in [root] + root._get_all_children():
                if (
                    node.is_terminal
                    and node.depth < max_depth
                    and node.data["feedback"]["exit_code"] != 0
                ):
                    candidates.append(node)
            if not candidates:
                break

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_node: dict[concurrent.futures.Future, Node[TypespecData]] = {}
                for node in candidates:
                    messages = [init_message]
                    for n in node.get_trajectory():
                        messages.append(n.data["message"])
                        messages.append({"role": "user", "content": n.data["feedback"]["stdout"]})
                    for _ in range(branch_factor):
                        future_to_node[executor.submit(
                            SearchPolicy.run_typespec,
                            messages,
                            self.client,
                            self.compiler,
                            self._model
                        )] = node
                for future in concurrent.futures.as_completed(future_to_node):
                    node = future_to_node[future]
                    result = future.result()
                    score = 1 if result["feedback"]["exit_code"] == 0 else 0
                    child = Node(result, score, parent=node)
                    node.children.append(child)
        return root.best_solution()
    
    @staticmethod
    def run_drizzle(
        messages: list[dict],
        client: AnthropicBedrock,
        compiler: CompilerService,
        model: str,
    ) -> DrizzleData:
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            messages=messages,
        )
        output = stages.drizzle.parse_output(response.content[0].text)
        feedback = compiler.compile_drizzle(output["drizzle_schema"])
        return {
            "message": {"role": "assistant", "content": response.content[0].text},
            "output": output,
            "feedback": feedback,
        }
    
    def bfs_drizzle(
        self,
        init_message: dict,
        root: Node[DrizzleData],
        max_depth: int = 3,
        branch_factor: int = 3,
        max_workers: int = 5,
    ) -> Node[DrizzleData]:
        while True:
            if root.best_solution().score == 1:
                break
            
            candidates: list[Node[DrizzleData]] = []
            for node in [root] + root._get_all_children():
                if (
                    node.is_terminal
                    and node.depth < max_depth
                    and node.data["feedback"]["stderr"],
                ):
                    candidates.append(node)
            if not candidates:
                break

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_node: dict[concurrent.futures.Future, Node[DrizzleData]] = {}
                for node in candidates:
                    messages = [init_message]
                    for n in node.get_trajectory():
                        messages.append(n.data["message"])
                        messages.append({"role": "user", "content": n.data["feedback"]["stderr"]})
                    for _ in range(branch_factor):
                        future_to_node[executor.submit(
                            SearchPolicy.run_drizzle,
                            messages,
                            self.client,
                            self.compiler,
                            self._model
                        )] = node
                for future in concurrent.futures.as_completed(future_to_node):
                    node = future_to_node[future]
                    result = future.result()
                    score = 1 if not result["feedback"]["stderr"] else 0
                    child = Node(result, score, parent=node)
                    node.children.append(child)
        return root.best_solution()
    
    @staticmethod
    def run_router(
        messages: list[dict],
        client: AnthropicBedrock,
        model: str,
    ):
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            messages=messages,
            tools = stages.router.TOOLS
        )
        return stages.router.parse_outputs([content for content in response.content])
    
    @staticmethod
    def run_preprocessor(
        messages: list[dict],
        client: AnthropicBedrock,
        model: str,
    ):
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            messages=messages,
        )
        return stages.processors.parse_output(response.content[0].text)
    
    @staticmethod
    def run_handler(
        messages: list[dict],
        client: AnthropicBedrock,
        model: str,
    ):
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            messages=messages,
        )
        return stages.handlers.parse_output(response.content[0].text)
