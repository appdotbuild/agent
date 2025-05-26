from fire import Fire
import ujson as json
from typing import List, Dict, Any

from core.statemachine import StateMachine, State
from trpc_agent.application import ApplicationContext, FSMEvent, MachineCheckpoint, FSMApplication, Node, EditActor
from trpc_agent.actors import BaseActor, ConcurrentActor, DraftActor
from llm.common import Message
import anyio

async def _get_actors(path):
    with open(path, "r") as f:
        data: MachineCheckpoint = json.load(f)
        root = await FSMApplication.make_states()
        fsm = await StateMachine[ApplicationContext, FSMEvent].load(root, data, ApplicationContext)
        match fsm.root.states:
            case None:
                raise ValueError("No states found in the FSM data.")
            case _:
                actors = [
                    state.invoke['src']
                    for state in fsm.root.states.values()
                    if state.invoke is not None
                ]
                return actors


def get_all_trajectories(root: Node, prefix: str = ""):
    nodes = list(filter(lambda x: x.is_leaf, root.get_all_children()))
    for i, n in enumerate(nodes):
        leaf_messages = []
        for traj_node in n.get_trajectory():
            leaf_messages.extend(traj_node.data.messages)

        yield f"{prefix}_{i}", [msg.to_dict() for msg in leaf_messages]


def main(path: str):
    actors = anyio.run(_get_actors, path)
    messages = {}

    for actor in actors:
        match actor:
            case ConcurrentActor():
                handlers = actor.handlers
                for name, handler in handlers.handlers.items():
                    for k, v in get_all_trajectories(handler, f"backend_{name}"):
                        messages[k] = v

                frontend = actor.frontend.root
                if frontend:
                    for k, v in get_all_trajectories(frontend, "frontend"):
                        messages[k] = v

            case DraftActor():
                root = actor.root
                if root is None:
                    continue
                for k, v in get_all_trajectories(root, "draft"):
                    messages[k] = v

            case EditActor():
                root = actor.root
                if root is None:
                    continue
                for k, v in get_all_trajectories(root, "edit"):
                    messages[k] = v

            case _:
                raise ValueError(f"Unknown actor type: {type(actor)}")

    print(json.dumps(messages))  # so it is `| jq` friendly


if __name__ == "__main__":
    Fire(main)
