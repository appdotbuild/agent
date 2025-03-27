from application import Application
from compiler.core import Compiler
import os
import coloredlogs
import logging
from fire import Fire
from core.interpolator import Interpolator
from fsm_core.llm_common import get_sync_client, CacheMode
from common import get_logger
import tempfile
import uuid

logger = get_logger(__name__)



def main(initial_description: str, mode: CacheMode = "replay"):
    """Full bot creation and update workflow"""
    # Use the correct Docker image names from prepare_containers.sh
    compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
    client = get_sync_client(cache_mode=mode)
    application = Application(client, compiler)

    bot_id = str(uuid.uuid4().hex)
    prepared_bot = application.prepare_bot([initial_description], bot_id=bot_id)
    my_bot = application.update_bot(typespec_schema=prepared_bot.typespec.typespec_definitions or "", bot_id=bot_id, capabilities=prepared_bot.capabilities.capabilities or [])

    with tempfile.TemporaryDirectory() as temp_dir:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        interpolator = Interpolator(current_dir)
        # Only use bake with ApplicationOut, not ApplicationPrepareOut
        interpolator.bake(my_bot, temp_dir)
        # run docker compose up in the dir and later down
        os.chdir(temp_dir)
        os.system('docker compose -p smoke_test up --build -d ')
        os.system('docker compose down')
        os.chdir(current_dir)

if __name__ == "__main__":
    Fire(main)
