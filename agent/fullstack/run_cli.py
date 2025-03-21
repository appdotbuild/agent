from typing import Literal
import os
import dagger
from dagger import dag
from anthropic import AsyncAnthropic
import statemachine
import backend_fsm
import frontend_fsm
from shared_fsm import ModelParams
import logic
import pickle


async def checkpoint_context(context: dict, export_dir: str, stage: Literal["backend", "frontend"]):
    match stage:
        case "backend":
            ckpt_path = os.path.join(export_dir, "checkpoint_backend.pkl")
            files_path = os.path.join(export_dir, "server", "src")
        case "frontend":
            ckpt_path = os.path.join(export_dir, "checkpoint_frontend.pkl")
            files_path = os.path.join(export_dir, "client", "src")
    with open(ckpt_path, "wb") as f:
        serializable = {k: v for k, v in context.items() if not isinstance(v, logic.Node)}
        pickle.dump(serializable, f, pickle.HIGHEST_PROTOCOL)
    if "checkpoint" in context:
        await context["checkpoint"].data["workspace"].container().directory("src").export(files_path)
    else:
        if "error" in context:
            raise context["error"]
        raise RuntimeError("Unhandled exception, context dumped.")


async def run_agent(export_dir: str, num_beams: int = 3):
    m_client = AsyncAnthropic()
    backend_m_params: ModelParams = {
        "model": "claude-3-7-sonnet-20250219",
        "max_tokens": 8192,
    }
    frontend_m_params: ModelParams = {
        "model": "claude-3-7-sonnet-20250219",
        "max_tokens": 8192,
        "tools": frontend_fsm.WS_TOOLS,
    }
    async with dagger.connection(dagger.Config(log_output=open(os.devnull, "w"))):
        if not os.path.exists(export_dir):
            print("Creating workspace...")
            await dag.host().directory("./prefabs/trpc_fullstack").export(export_dir)
        else:
            print("Using existing workspace...")

        b_states = await backend_fsm.make_fsm_states(m_client, backend_m_params, beam_width=num_beams)
        b_context: backend_fsm.AgentContext = {
            "user_prompt": input("What are we building?\n"),
        }
        b_fsm = statemachine.StateMachine[backend_fsm.AgentContext](b_states, b_context)
        print("Generating blueprint...")
        await b_fsm.send(backend_fsm.FSMEvent.PROMPT)
        await checkpoint_context(b_fsm.context, export_dir, "backend")
        print("Generating logic...")
        await b_fsm.send(backend_fsm.FSMEvent.CONFIRM)
        await checkpoint_context(b_fsm.context, export_dir, "backend")
        print("Generating server...")
        await b_fsm.send(backend_fsm.FSMEvent.CONFIRM)
        await checkpoint_context(b_fsm.context, export_dir, "backend")

        f_context: frontend_fsm.AgentContext = {
            "user_prompt": b_context["user_prompt"],
            "backend_files": b_fsm.context["backend_files"],
            "frontend_files": {},
        }
        f_states = await frontend_fsm.make_fsm_states(m_client, frontend_m_params, beam_width=num_beams)
        f_fsm = statemachine.StateMachine[frontend_fsm.AgentContext](f_states, f_context)
        print("Generating frontend...")
        await f_fsm.send(frontend_fsm.FSMEvent.PROMPT)
        await checkpoint_context(f_fsm.context, export_dir, "frontend")
        while True:
            edit_prompt = input("Edits > ('done' to quit):\n")
            if edit_prompt == "done":
                break
            f_fsm.context["user_prompt"] = edit_prompt
            f_fsm.context.pop("bfs_frontend")
            print("Applying edits...")
            await f_fsm.send(frontend_fsm.FSMEvent.PROMPT)
            await checkpoint_context(f_fsm.context, export_dir, "frontend")
