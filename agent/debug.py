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

    # Create temporary directory and application
    tempdir = tempfile.TemporaryDirectory()
    application = Application(client, compiler, "templates", tempdir.name)

    # Create bot
    my_bot = application.create_bot(initial_description)
    print("Bot created:", my_bot)
    print("\nGherkin:", my_bot.gherkin)
    print("\nGeneration directory:", application.generation_dir)

    if final_directory:
        logger.info(f"Copying generation directory to {final_directory}")
        shutil.rmtree(final_directory, ignore_errors=True)
        shutil.copytree(application.generation_dir, final_directory)

    # Run npm install and TypeScript compilation
    app_schema_dir = os.path.join(application.generation_dir, 'app_schema')
    os.chdir(app_schema_dir)
    os.system('npm install')
    os.system('npx tsc --noEmit')
    os.chdir('..')

    # # Generate typespec
    # typespec = application._make_typespec(application_description)
    # print("\nTypespec:", typespec)

    # # Generate TypeScript schema
    # typescript_schema = application._make_typescript_schema(typespec.typespec_definitions)
    # print("\nTypeScript schema:", typescript_schema)

    # # Generate Drizzle schema
    # drizzle = application._make_drizzle(typespec.typescript_schema)
    # print("\nDrizzle details:")
    # print("Error output:", drizzle.error_output)
    # print("Reasoning:", drizzle.reasoning)
    # print("Schema:", drizzle.drizzle_schema)

    # # Generate router
    # router = application._make_router(typespec.data.output.typespec_definitions)
    # print("\nRouter details:")
    # print("Score:", router.score)
    # print("Output:", router.data.output)

    # # Generate handlers
    # handlers = application._make_handlers(
    #     typespec.data.output.llm_functions,
    #     typespec.data.output.typespec_definitions,
    #     typescript_schema.data.output.typescript_schema,
    #     drizzle.data.output.drizzle_schema,
    # )

    # # Print handler details
    # print("\nHandler details:")
    # for name, handler in handlers.items():
    #     print(f"\nHandler: {name}")
    #     print(f"Score: {handler.score}")
    #     print(f"Depth: {handler.depth}")
    #     print(f"Output: {handler.data.output}")
    #     if handler.score != 1:
    #         print(f"Feedback: {handler.data.output.feedback['stdout']}")

if __name__ == "__main__":
    Fire(main)
