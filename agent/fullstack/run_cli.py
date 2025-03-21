import os
import dagger
from dagger import dag
from anthropic import AsyncAnthropicBedrock
import statemachine
import backend_fsm
import frontend_fsm
from shared_fsm import ModelParams
import logic
import pickle


def checkpoint_context(context: dict, path: str):
    with open(path, "wb") as f:
        serializable = {k: v for k, v in context.items() if not isinstance(v, logic.Node)}
        pickle.dump(serializable, f)


async def run_agent(export_dir: str):
    m_client = AsyncAnthropicBedrock(aws_profile="dev", aws_region="us-west-2")
    backend_m_params: ModelParams = {
        "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        "max_tokens": 8192,
    }
    frontend_m_params: ModelParams = {
        "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        "max_tokens": 8192,
        "tools": frontend_fsm.WS_TOOLS,
    }
    async with dagger.connection(dagger.Config(log_output=open(os.devnull, "w"))):
        if not os.path.exists(export_dir):
            print("Creating workspace...")
            await dag.host().directory("./prefabs/trpc_fullstack").export(export_dir)
        else:
            print("Using existing workspace...")

        b_states = await backend_fsm.make_fsm_states(m_client, backend_m_params, beam_width=3)
        b_context: backend_fsm.AgentContext = {
            "user_prompt": input("What are we building?\n"),
        }
        b_fsm = statemachine.StateMachine[backend_fsm.AgentContext](b_states, b_context)
        print("Generating blueprint...")
        await b_fsm.send(backend_fsm.FSMEvent.PROMPT)
        checkpoint_context(b_fsm.context, export_dir + "/checkpoint_backend.pkl")
        await b_fsm.context["checkpoint"].data["workspace"].container().directory("src").export(export_dir + "/server/src")
        print("Generating logic...")
        await b_fsm.send(backend_fsm.FSMEvent.CONFIRM)
        checkpoint_context(b_fsm.context, export_dir + "/checkpoint_backend.pkl")
        await b_fsm.context["checkpoint"].data["workspace"].container().directory("src").export(export_dir + "/server/src")
        print("Generating server...")
        await b_fsm.send(backend_fsm.FSMEvent.CONFIRM)
        checkpoint_context(b_fsm.context, export_dir + "/checkpoint_backend.pkl")
        await b_fsm.context["checkpoint"].data["workspace"].container().directory("src").export(export_dir + "/server/src")

        f_context: frontend_fsm.AgentContext = {
            "user_prompt": b_context["user_prompt"],
            "backend_files": b_fsm.context["backend_files"],
            "frontend_files": {},
        }
        f_states = await frontend_fsm.make_fsm_states(m_client, frontend_m_params, beam_width=3)
        f_fsm = statemachine.StateMachine[frontend_fsm.AgentContext](f_states, f_context)
        print("Generating frontend...")
        await f_fsm.send(frontend_fsm.FSMEvent.PROMPT)
        checkpoint_context(b_fsm.context, export_dir + "/checkpoint_frontend.pkl")
        await f_fsm.context["checkpoint"].data["workspace"].container().directory("src").export(export_dir + "/client/src")
        while True:
            edit_prompt = input("Edits > ('done' to quit):\n")
            if edit_prompt == "done":
                break
            f_fsm.context["user_prompt"] = edit_prompt
            f_fsm.context.pop("bfs_frontend")
            print("Applying edits...")
            await f_fsm.send(frontend_fsm.FSMEvent.PROMPT)
            checkpoint_context(f_fsm.context, export_dir + "/checkpoint_frontend.pkl")
            await f_fsm.context["checkpoint"].data["workspace"].container().directory("src").export(export_dir + "/client/src")
