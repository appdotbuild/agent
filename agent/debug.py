from application import Application
from compiler.core import Compiler
import os
import coloredlogs
import logging
from fire import Fire
from core.interpolator import Interpolator
from fsm_core.llm_common import get_sync_client


logger = logging.getLogger(__name__)

coloredlogs.install(level='INFO')



def prepare_only(initial_description: str):
    """Just test the prepare_bot functionality"""
    compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
    client = get_sync_client()
    application = Application(client, compiler)

    my_bot = application.prepare_bot([initial_description])
    print("Bot prepared:", my_bot)
    return my_bot

def main(initial_description: str, final_directory: str | None = None, update: bool = True):
    """Full bot creation and update workflow"""
    # Use the correct Docker image names from prepare_containers.sh
    compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
    client = get_sync_client()
    application = Application(client, compiler)

    my_bot = application.prepare_bot([initial_description])
    print("Bot prepared successfully!")
    
    if update:
        # Format the typespec definitions with the required tags for parse_output
        formatted_typespec = f"<reasoning>{my_bot.typespec.reasoning}</reasoning>\n<typespec>{my_bot.typespec.typespec_definitions}</typespec>"
        my_bot = application.update_bot(formatted_typespec)
        print("Bot updated successfully!")

        if final_directory:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            interpolator = Interpolator(current_dir)
            # Only use bake with ApplicationOut, not ApplicationPrepareOut
            interpolator.bake(my_bot, final_directory)
            # run docker compose up in the dir and later down
            os.chdir(final_directory)
            os.system('docker compose up --build -d')
            os.system('docker compose down')
            os.chdir('..')
    elif not update and final_directory:
        print("Cannot call bake on ApplicationPrepareOut, please use update=True for baking.")

if __name__ == "__main__":
    Fire(main)
