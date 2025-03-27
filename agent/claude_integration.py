import os
import uuid
import shutil
import tempfile
import logging
import requests
import socket
from typing import List, Dict, Any, Tuple, Optional
from anthropic import AnthropicBedrock
from anthropic.types import MessageParam
from api.fsm_tools import FSMToolProcessor, run_with_claude
from core.interpolator import Interpolator
from application import Application, InteractionMode
from langfuse import Langfuse
from compiler.core import Compiler

logger = logging.getLogger(__name__)

def generate_bot_with_claude(
    client: AnthropicBedrock,
    compiler: Compiler,
    write_url: str, 
    read_url: str, 
    prompts: list[str], 
    trace_id: str, 
    bot_id: Optional[str] = None, 
    capabilities: Optional[list[str]] = None
):
    """Generate a bot using the Claude agent loop with FSM tools"""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            application = Application(client, compiler, interaction_mode=InteractionMode.NON_INTERACTIVE)
            interpolator = Interpolator(".")
            fsm_processor = FSMToolProcessor()
            
            logger.info(f"Creating bot with prompts: {prompts}")
            prompt_texts = [getattr(p, 'prompt', p) for p in prompts]
            
            initial_prompt = f"""Generate a TypeScript application based on the following prompt(s):
            {' '.join(prompt_texts)}
            """
            
            current_messages = [{
                "role": "user",
                "content": initial_prompt
            }]
            is_complete = False
            
            while not is_complete:
                current_messages, is_complete = run_with_claude(
                    fsm_processor,
                    client,
                    current_messages
                )
                logger.info(f"Claude agent loop iteration completed: {len(current_messages) - 1}")
            
            logger.info("FSM interaction completed, retrieving final outputs")
            completion_result = fsm_processor.tool_complete_fsm()
            
            if not completion_result.success:
                logger.error(f"Error completing FSM: {completion_result.error}")
                raise ValueError(f"Failed to complete FSM: {completion_result.error}")
            
            if completion_result.data is None:
                raise ValueError("FSM completion returned no data")
                
            bot_data = completion_result.data.get("final_outputs", {})
            
            typespec_schema = bot_data.get("typespec", {}).get("typespec_definitions", "")
            
            bot = application.update_bot(typespec_schema, bot_id, langfuse_observation_id=trace_id, capabilities=capabilities)
            
            interpolator.bake(bot, tmpdir)
            logger.info(f"Baked bot to {tmpdir}")
            
            zip_path = shutil.make_archive(
                base_name=tmpdir,
                format="zip",
                root_dir=tmpdir,
            )
            with open(zip_path, "rb") as f:
                upload_result = requests.put(write_url, data=f.read())
                upload_result.raise_for_status()
                logger.info(f"Successfully uploaded bot to {write_url}")
                
            return {"status": "success", "message": "Bot generated successfully"}
    except Exception as e:
        logger.exception(f"Error generating bot with Claude: {str(e)}")
        raise
