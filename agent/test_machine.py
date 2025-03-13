import unittest

from statemachine import StateMachine, State

# A dummy actor that records its execution.
class DummyActor:
    def __init__(self, log: list[str]):
        self.log = log
    def execute(self, context):
        self.log.append("actor_executed")

class FSMTests(unittest.TestCase):
    def test_basic_transition(self):
        log: list[str] = []

        def enter_A(ctx): 
            log.append("enter_A")
        def exit_A(ctx): 
            log.append("exit_A")
        def enter_B(ctx): 
            log.append("enter_B")
        def enter_C(ctx):
            log.append("enter_C")

        # Basic FSM with a simple transition from A to B.
        root: State = {
            "on": {"start": "A"},
            "states": {
                "A": {
                    "entry": [enter_A],
                    "exit": [exit_A],
                    "on": {"go": "B", "jump": "C"},
                    "states": {
                        "B": {
                            "entry": [enter_B]
                        }
                    }
                },
                "C": {
                    "entry": [enter_C]
                }
            }
        }
        fsm = StateMachine(root, {})
        # Transition from root to "A"
        fsm.send("start")
        self.assertEqual(log, ["enter_A"])

        # Transition from "A" to "B"
        fsm.send("go")
        self.assertEqual(log, ["enter_A", "enter_B"])

        # Transition from "A" to "C"
        fsm.send("jump")
        self.assertEqual(log, ["enter_A", "enter_B", "exit_A", "enter_C"])

    def test_invoke_transition(self):
        log: list[str] = []

        def enter_A(ctx): 
            log.append("enter_A")
        def enter_B(ctx): 
            log.append("enter_B")
        def invoke_done_action(ctx, res): 
            log.append("invoke_done")

        dummy_actor = DummyActor(log)
        
        # Set up a FSM where state A has an invoke that
        # calls the dummy actor and on completion transitions to B.
        root: State = {
            "on": {"start": "A"},
            "states": {
                "A": {
                    "entry": [enter_A],
                    "invoke": {
                        "src": dummy_actor,
                        "input_fn": lambda ctx: ctx,
                        "on_done": {
                            "target": "B",
                            "actions": [invoke_done_action]
                        }
                    },
                    "states": {
                        "B": {
                            "entry": [enter_B]
                        }
                    }
                }
            }
        }
        fsm = StateMachine(root, {})
        fsm.send("start")
        self.assertEqual(
            log,
            [
                "enter_A",        # entry of A
                "actor_executed",   # dummy actor execute call
                "invoke_done",      # action after invoke on_done
                "enter_B"           # entry of B
            ]
        )

    def test_always_transition(self):
        log: list[str] = []

        def enter_A(ctx): 
            log.append("enter_A")
        def always_action(ctx): 
            value = ctx.get("value", 0)
            ctx["value"] = value + 1
            log.append("always_action")
        def guard(ctx):
            return ctx.get("value", 0) < 2

        # Set up an FSM where state A always transitions to B if the guard passes.
        root: State = {
            "on": {"start": "A"},
            "states": {
                "A": {
                    "entry": [enter_A],
                    "always": {
                        "target": "A",
                        "guard": guard,
                        "actions": [always_action]
                    },
                }
            }
        }
        fsm = StateMachine(root, {})
        fsm.send("start")
        self.assertEqual(
            log,
            [
                "enter_A",          # entry of A
                "always_action",    # always actions executed
                "enter_A",          # second entry of A
                "always_action",    # second always action executed and guard fails
                "enter_A"           # third entry of A
            ]
        )

if __name__ == '__main__':
    unittest.main()