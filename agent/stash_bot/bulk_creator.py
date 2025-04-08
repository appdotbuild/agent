from anthropic import AnthropicBedrock
from application import Application
from compiler.core import Compiler
import tempfile
import coloredlogs
import logging
from fire import Fire
import shutil
import os
from core.interpolator import Interpolator


logger = logging.getLogger(__name__)

coloredlogs.install(level="INFO")


ideas = (
    (
        "PlantBot",
        "hey can u make me a bot that tracks my plants? like when i water them and stuff... need it to remind me when to water next",
    ),
    (
        "ComicBot",
        "Generate a bot to manage my comic book collection - should track titles, issues, and value estimates. Thanks!",
    ),
    (
        "HomeworkBot",
        "need bot 4 tracking my kids homework assignments & due dates... must be simple 2 use!",
    ),
    (
        "WardrobeBot",
        "Can you create a bot that suggests outfit combinations from my wardrobe? I want to input my clothes and get daily suggestions",
    ),
    (
        "SpanishBot",
        "make me a bot that helps me practice spanish! should ask me random words daily and track my progress",
    ),
    (
        "GameBot",
        "Generate chatbot to manage my board game nights - need to track who's coming, which games we're bringing, and keep score",
    ),
    (
        "CoffeeBot",
        "I want a bot that tracks my coffee consumption and tells me fun facts about coffee everytime i log a cup!",
    ),
    (
        "RecipeBot",
        "create me a bot that keeps track of my favorite recipes and suggests what to cook based on ingredients i have at home",
    ),
    (
        "MedsBot",
        "Need simple bot that helps me track my medication schedule & reminds me when to take pills... thx!",
    ),
    (
        "MoodBot",
        "make me a bot that gives me daily positive affirmations and tracks my mood over time please :)",
    ),
)


def main(prefix: str, save_dir: str | None = None):
    compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
    client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")

    for name, prompt in ideas:
        print(prompt)

        application = Application(client, compiler)

        # First prepare the bot
        prepared_bot = application.prepare_bot([prompt], f"{prefix}_{name}")
        # Then update with the prepared bot's typespec
        my_bot = application.update_bot(prepared_bot.typespec.typespec_definitions, f"{prefix}_{name}")
        print("Bot created:", my_bot)

        if save_dir:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            interpolator = Interpolator(current_dir)
            
            bot_dir = os.path.join(save_dir, f"{prefix}_{name}")
            os.makedirs(bot_dir, exist_ok=True)
            
            interpolator.bake(my_bot, bot_dir)

            app_schema_dir = os.path.join(bot_dir, 'app_schema')
            os.chdir(app_schema_dir)
            os.system('npm install')
            os.system('npx tsc --noEmit')
            os.chdir('..')


if __name__ == "__main__":
    Fire(main)
