from typing import Literal
import os
import pickle
import dagger
from dagger import dag
import logic
import statemachine
import backend_fsm
from shared_fsm import ModelParams
from anthropic import AsyncAnthropicBedrock
from models.anthropic_bedrock import AnthropicLLM

import anyio
from fastapi import FastAPI



async def run_agent(num_beams: int = 1):
    m_client = AnthropicLLM(AsyncAnthropicBedrock(aws_profile="dev", aws_region="us-west-2"))
    backend_m_params: ModelParams = {
        "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        "max_tokens": 8192,
    }
    async with dagger.connection(dagger.Config(log_output=open(os.devnull, "w"))):
        b_states = await backend_fsm.make_fsm_states(m_client, backend_m_params, beam_width=num_beams)
        b_context: backend_fsm.AgentContext = {
            "user_prompt": "simple note taking app",
        }
        b_fsm = statemachine.StateMachine[backend_fsm.AgentContext](b_states, b_context)
        print("Generating blueprint...")
        await b_fsm.send(backend_fsm.FSMEvent.PROMPT)


if __name__ == "__main__":
    anyio.run(run_agent)
