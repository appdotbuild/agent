from anthropic import AnthropicBedrock
from application import Application, feature_flags
from compiler.core import Compiler
import os
import coloredlogs
import logging
from fire import Fire
from core.interpolator import Interpolator


logger = logging.getLogger(__name__)

coloredlogs.install(level='INFO')



def main(initial_description: str, final_directory: str | None = None):
    compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
    client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")
    application = Application(client, compiler)

    my_bot = application.create_bot(initial_description)
    print("Bot created:", my_bot)

    if final_directory:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        interpolator = Interpolator(current_dir)
        interpolator.bake(my_bot, final_directory)

        # Run npm install and TypeScript compilation as smoke test
        app_schema_dir = os.path.join(final_directory, 'app_schema')
        os.chdir(app_schema_dir)
        os.system('npm install')
        os.system('npx tsc --noEmit')
        os.chdir('..')

if __name__ == "__main__":
    Fire(main)
