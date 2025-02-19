from anthropic import AnthropicBedrock
from application import Application
from compiler.core import Compiler
import tempfile
import os
import coloredlogs
import logging
from fire import Fire
import shutil


logger = logging.getLogger(__name__)

coloredlogs.install(level='INFO')



def main(initial_description: str, final_directory: str | None = None):
    compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
    client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")

    tempdir = tempfile.TemporaryDirectory()
    application = Application(client, compiler, "templates", tempdir.name)

    my_bot = application.create_bot(initial_description)
    print("Bot created:", my_bot)
    print("\nGherkin:", my_bot.gherkin)
    print("\nGeneration directory:", application.generation_dir)

    if final_directory:
        logger.info(f"Copying generation directory to {final_directory}")
        shutil.rmtree(final_directory, ignore_errors=True)
        shutil.copytree(application.generation_dir, final_directory)

    # Run npm install and TypeScript compilation as smoke test
    app_schema_dir = os.path.join(application.generation_dir, 'app_schema')
    os.chdir(app_schema_dir)
    os.system('npm install')
    os.system('npx tsc --noEmit')
    os.chdir('..')

if __name__ == "__main__":
    Fire(main)
