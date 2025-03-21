from typing import Any, Callable, NotRequired, Protocol, TypedDict


class Actor(Protocol):
    def execute(self, *args, **kwargs) -> Any:
        ...


class InvokeCallback[T](TypedDict):
    target: str
    actions: NotRequired[list[Callable[[T, Any], Any]]] # = []


class Invoke[T](TypedDict):
    src: Actor
    input_fn: Callable[[T], Any]
    on_done: NotRequired[InvokeCallback]
    on_error: NotRequired[InvokeCallback]


class AlwaysRun[T](TypedDict):
    target: str
    guard: NotRequired[Callable[[T], bool]]
    actions: NotRequired[list[Callable[[T], Any]]]


class State[T](TypedDict):
    entry: NotRequired[list[Callable[[T], Any]]]
    invoke: NotRequired[Invoke[T]]
    on: NotRequired[dict[str, str]]
    exit: NotRequired[list[Callable[[T], Any]]]
    always: NotRequired[AlwaysRun[T] | list[AlwaysRun[T]]]
    states: NotRequired[dict[str, "State[T]"]]
    initial: NotRequired[str]


class StateMachine[T]:
    def __init__(self, root: State, context: T):
        self.root = root
        self.context = context
        self.state_stack: list[State[T]] = [root]
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
            if "states" not in parent_state or next_state not in parent_state["states"]:
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
    
    def _run_entry(self, state: State[T]):
        if "entry" in state:
            for action in state["entry"]:
                action(self.context)
    
    def _run_exit(self, state: State[T]):
        if "exit" in state:
            for action in state["exit"]:
                action(self.context)
    
    def _run_invoke(self, state: State[T]):
        if "invoke" in state:
            invoke = state["invoke"]
            try:
                args = invoke["input_fn"](self.context)
                event = invoke["src"].execute(*args)
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
    
    def _run_always(self, state: State[T]):
        if "always" in state:
            branches = state["always"] if isinstance(state["always"], list) else [state["always"]]
            for always in branches:
                if "guard" not in always or always["guard"](self.context):
                    self._queued_transition = always["target"]
                    for action in always.get("actions", []):
                        action(self.context)
                    return
