from typing import Any, Callable, NotRequired, Protocol, TypedDict


class Actor(Protocol):
    def execute(self, context: Any) -> Any:
        ...


class InvokeCallback(TypedDict):
    target: str
    actions: NotRequired[list[Callable[[Any, Any], Any]]] # = []


class Invoke(TypedDict):
    src: Actor
    input_fn: Callable[[Any], Any]
    on_done: NotRequired[InvokeCallback]
    on_error: NotRequired[InvokeCallback]


class AlwaysRun(TypedDict):
    target: str
    guard: NotRequired[Callable[[Any], bool]]
    actions: NotRequired[list[Callable[[Any], Any]]]


class State(TypedDict):
    entry: NotRequired[list[Callable[[Any], Any]]]
    invoke: NotRequired[Invoke]
    on: NotRequired[dict[str, str]]
    exit: NotRequired[list[Callable[[Any], Any]]]
    always: NotRequired[AlwaysRun]
    states: NotRequired[dict[str, "State"]]
    initial: NotRequired[str]


class StateMachine:
    def __init__(self, root: State, context: Any):
        self.root = root
        self.context = context
        self.state_stack: list[State] = [root]
        self._queued_transition: str | None = None
    
    def send(self, event: str):
        for state in reversed(self.state_stack):
            if "on" in state and event in state["on"]:
                self._queued_transition = state["on"][event]
                self._process_transitions()
                return
        raise RuntimeError(f"Invalid event: {event}, stack: {self.stack_path}")
    
    def _process_transitions(self):
        while self._queued_transition:
            print("Processing transition:", self.stack_path, self._queued_transition)
            next_state = self._queued_transition
            self._queued_transition = None
            self._transition(next_state)
    
    def _transition(self, next_state: str):
        exit_stack = []
        while self.state_stack:
            parent_state = self.state_stack.pop()
            if next_state not in parent_state.get("states", {}):
                exit_stack.append(parent_state)
                continue
            target_state = parent_state["states"][next_state]
            for state in reversed(exit_stack):
                self._run_exit(state)
            self._run_entry(target_state)
            self._run_invoke(target_state)
            self._run_always(target_state)
            self.state_stack.extend([parent_state, target_state]) # put target state on stack
            return
        self.state_stack.extend(reversed(exit_stack)) # restore stack
        raise RuntimeError(f"Invalid transition: {next_state}, stack: {self.stack_path}")
    
    @property
    def stack_path(self) -> list[str]:
        path = []
        for p, n in zip(self.state_stack, self.state_stack[1:]):
            if "states" not in p:
                break
            for key, value in p["states"].items():
                if value == n:
                    path.append(key)
                    break
        return path
    
    def _run_entry(self, state: State):
        if "entry" in state:
            for action in state["entry"]:
                action(self.context)
    
    def _run_exit(self, state: State):
        if "exit" in state:
            for action in state["exit"]:
                action(self.context)
    
    def _run_invoke(self, state: State):
        if "invoke" in state:
            invoke = state["invoke"]
            try:
                event = invoke["src"].execute(invoke["input_fn"](self.context))
                if "on_done" in invoke:
                    self._queued_transition = invoke["on_done"]["target"]
                    for action in invoke["on_done"].get("actions", []):
                        action(self.context, event)
            except Exception as e:
                if "on_error" in invoke:
                    self._queued_transition = invoke["on_error"]["target"]
                    for action in invoke["on_error"].get("actions", []):
                        action(self.context, e)
                else:
                    raise e
    
    def _run_always(self, state: State):
        if "always" in state:
            always = state["always"]
            if "guard" not in always or always["guard"](self.context):
                self._queued_transition = always["target"]
                for action in always.get("actions", []):
                    action(self.context)


def not_impl(ctx):
    raise NotImplementedError("Not implemented")


machine: State = {
    "on": {
        "START": "typespec",
    },
    "states": {
        "typespec": {
            "on": {
                "PROMPT": "adjust",
                "CONFIRM": "core",
            },
            "states": {
                "init": {},
                "adjust": {
                    "entry": [not_impl],
                },
            }
        },
        "core": {
            "states": {
                "drizzle": {},
                "typescript": {},
                "handler_tests": {},
                "handlers": {},
            }
        },
        "complete": {
            "on": {
                "PROMPT": "edit_application",
            }
        },
        "failure": {
            "entry": [not_impl],
        },
        "edit_application": {
            "entry": [not_impl],
        },
    }
}