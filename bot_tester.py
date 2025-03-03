import os
import re
import shutil
import time
import subprocess
import uuid
import random
import string
import logging
from typing import Dict, List, Any, Literal
import docker
from fire import Fire
from anthropic import AnthropicBedrock
import coloredlogs
import httpx
from agent.application import Application
from agent.compiler.core import Compiler
from agent.core.interpolator import Interpolator
import joblib as jl
import json


# set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
coloredlogs.install(level='INFO')
# silence noisy loggers
logging.getLogger('botocore').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)


BotRating = Literal["awful", "not cool", "fine", "great"]


def _parse_tag(msg, tag="errors"):
    pattern = re.compile(f"<{tag}>(.*?)</{tag}>", re.DOTALL)
    match = pattern.search(msg)
    if match is None:
        return None
    return match.group(1).strip()


class BotTester:
    def __init__(self, aws_profile="dev", aws_region="us-west-2", output_dir: str = '/tmp/bot_eval/'):
        self.client = AnthropicBedrock(aws_profile=aws_profile, aws_region=aws_region)
        self.compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
        self.application = Application(self.client, self.compiler)
        self.user_id = str(uuid.uuid4())
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.port = random.randint(8000, 9000)
        self.env = os.environ.copy()
        self.httpx_client = httpx.Client()

    def generate_bot(self, prompt: str, bot_name: str) -> str:
        bot_dir = os.path.join(self.output_dir, bot_name)
        if os.path.exists(bot_dir):
            logger.info(f"Bot directory already exists: {bot_dir}")
            if os.path.isdir(bot_dir) and os.path.exists(os.path.join(bot_dir, "app_schema")):
                logger.info(f"Bot directory is valid: {bot_dir}")
                return bot_dir
            else:
                logger.info(f"Bot directory is invalid: {bot_dir}, deleting")
                shutil.rmtree(bot_dir)

        logger.info(f"Generating bot with prompt: {prompt}")
        my_bot = self.application.create_bot(prompt)
        logger.info(f"Bot created successfully")
        
        current_dir = os.path.dirname(os.path.abspath(__file__))        
        interpolator = Interpolator(os.path.join(current_dir, "agent"))
        interpolator.bake(my_bot, bot_dir)
        
        logger.info(f"Bot files generated in {bot_dir}")
        return bot_dir
    
    def run_bot(self, bot_dir: str) -> None:
        """Run the bot using docker-compose with randomized container names"""
        if not bot_dir:
            raise ValueError("No bot has been generated yet")
        
        postfix = self._generate_random_name("_")

        self.env["APP_CONTAINER_NAME"] = "app_" + postfix
        self.env["POSTGRES_CONTAINER_NAME"] = "db_" + postfix
        self.env["NETWORK_NAME"] = "network_" + postfix
        self.env["RUN_MODE"] = "http-server"

        os.chdir(bot_dir)
        
        logger.info(f"Starting bot services with docker-compose, port {self.port} for the bot API")
        
        port_mapping = f"{self.port}:3000"
        self.env["BOT_PORT_MAPPING"] = port_mapping        
        cmd = ["docker", "compose", "up", "-d"]
        
        try:
            result = subprocess.run(cmd, check=True, env=self.env, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to start bot services: {result.stderr}")
                raise RuntimeError("Failed to start bot services")
                
            logger.info("Waiting for services to be ready")
            time.sleep(3) 
            
            client = docker.from_env()
            app_container = client.containers.get(self.env["APP_CONTAINER_NAME"])
            db_container = client.containers.get(self.env["POSTGRES_CONTAINER_NAME"])
            
            assert app_container.status == "running", f"App container is not running"
            assert db_container.status == "running", f"Database container is not running"
            
            os.chdir("..")
            logger.info("Bot is running")
            
        except Exception as e:
            os.chdir("..")  # Ensure we return to the original directory
            raise e
    
    def talk_to_bot(self, message: str) -> str:
        url = f"http://localhost:{self.port}/chat"
        payload = {
            "user_id": self.user_id,
            "message": message
        }

        logger.info(f"Sending message to bot at {url}, payload: {payload}")
        
        retries = 3
        for attempt in range(retries + 1):
            try:
                response = self.httpx_client.post(url, json=payload, timeout=30)
                response.raise_for_status()
                return response.json()["reply"]
            except Exception as e:
                if attempt < retries:
                    logger.info(f"attempt {attempt+1} failed, retrying in 5 seconds: {str(e)}")
                    time.sleep(5)
                else:
                    breakpoint()
                    raise
    
    def evaluate_experience(self, conversation: List[Dict[str, Any]], prompt: str) -> Dict[str, Any]:
        """Use the current Claude model to evaluate the bot interaction on a single axis"""
        logger.info("Evaluating bot conversation")
        
        # Create a prompt for the evaluation
        prompt = f"""You are an expert chatbot evaluator tasked with assessing the quality of conversations between users and custom chatbots. Your goal is to provide a fair and accurate evaluation based on the conversation provided.

First, review the original prompt used to create the chatbot:

<chatbot_prompt>
{prompt}
</chatbot_prompt>

Now, carefully examine the following conversation transcript:

<conversation_transcript>
{'\n\n'.join(conversation)}
</conversation_transcript>

To complete your evaluation, follow these steps:

1. Read the entire conversation thoroughly.

2. Evaluate the chatbot's performance based on these criteria:
   a) Relevance and accuracy of responses
   b) Ability to understand and address user queries
   c) Consistency and coherence throughout the conversation
   d) Overall helpfulness and user experience

3. Choose one of the following ratings that best describes the chatbot's performance:
   - "awful": The bot is completely broken or unhelpful
   - "not cool": The bot works but has significant issues
   - "fine": The bot works adequately but could be improved
   - "great": The bot performs extremely well

4. Provide a brief explanation (1-3 sentences) for your chosen rating, highlighting the key factors that influenced your decision.

Before providing your final evaluation, work through your evaluation process inside <evaluation_process> tags in your thinking block:

a) For each of the four evaluation criteria, quote 1-2 relevant parts of the conversation that demonstrate the chatbot's performance in that area.
b) For each rating option ("awful", "not cool", "fine", "great"), provide 2-3 arguments for and against using that rating based on the evidence from step a.
c) Tally up the strengths and weaknesses you've identified to support your final rating decision.

This will ensure a thorough and well-reasoned assessment.

Outside of your thinking block, format your final output as follows:

<rating>Your chosen rating</rating>
<explanation>Your 1-3 sentence explanation for the rating</explanation>

Example output structure (do not copy this content, it's just to illustrate the format):

<rating>fine</rating>
<explanation>The chatbot demonstrated adequate understanding of user queries and provided mostly relevant responses. However, there were instances where it could have been more helpful or accurate. Overall, it performed satisfactorily but has room for improvement.</explanation>

Your final output should consist only of the rating and explanation, and should not duplicate or rehash any of the work you did in the evaluation process."""
        
        # Get evaluation from the Claude model
        response = self.client.messages.create(
            model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            max_tokens=512 + 1024,
            messages=[{"role": "user", "content": prompt}], 
            thinking= {
                "type": "enabled",
                "budget_tokens": 1024,
            }
        )
        content = response.content[-1].text
        thinking = response.content[0].thinking
        rating = _parse_tag(content, "rating")
        explanation = _parse_tag(content, "explanation")
        
        return {
            "rating": rating,
            "explanation": explanation,
            "raw_response": content, 
            "thinking": thinking,
        }
    
    def stop_bot(self, bot_dir: str) -> None:
        os.chdir(bot_dir)
        
        logger.info("Stopping bot services...")
        try:
            subprocess.run(["docker", "compose", "down"], check=True, env=self.env)
            os.chdir("..")
            logger.info("Bot services stopped")
        except Exception as e:
            os.chdir("..")  # Ensure we return to the original directory
            logger.error(f"Error stopping bot services: {e}")
    
    def _generate_random_name(self, prefix: str, length: int = 8) -> str:
        return prefix + ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def eval_single_prompt(prompt: str, bot_name: str, messages: int = 10, keep_files: bool = True):
    tester = BotTester(aws_profile="dev", aws_region="us-west-2", output_dir="/tmp/bot_eval/")
    claude = tester.client

    bot_dir = tester.generate_bot(prompt, bot_name)
    try:
        tester.run_bot(bot_dir)        
        logger.info("Starting conversation with the bot")
        conversation = [
            {"role": "user", "content": "Chatbot: Hello, ready to serve you today!"}, 
        ]
        
        for i in range(messages):
            conversation.append({"role": "assistant", "content": "Test user:"})  # add prefilled assistant message
            response = claude.messages.create(
                model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
                messages=conversation, 
                temperature=1,
                max_tokens=1024,
                system=f"""You are a helpful assistant that emulates a human user that is testing a chatbot. The bot was created with the following prompt: {prompt}. Assistant acts as a somewhat grumpy and not that smart human user that is testing the chatbot, user acts as the chatbot. You should respond in a way that is natural and human-like, matching the user's tone and style based on the prompt, being casual, not too formal, not too verbose, use slangs.
                """
            )
            txt = response.content[0].text
            conversation.pop()  # remove prefilled assistant message
            conversation.append({"role": "assistant", "content": f"Test user: {txt}"})
            logger.debug(f"User message: {txt}")
            bot_response = tester.talk_to_bot(txt)
            conversation.append({"role": "user", "content": f"Chatbot: {bot_response}"})
            logger.debug(f"Bot response: {bot_response}")

        breakpoint()
        tester.stop_bot(bot_dir)

        conversation_text = [x["content"] for x in conversation]
        evaluation = tester.evaluate_experience(conversation_text, prompt)
        logger.info(f"Rating for {bot_name}: {evaluation['rating'].upper()}")
        logger.info(f"Explanation for {bot_name}: {evaluation['explanation']}")
        
        if keep_files:
            logger.info(f"Bot files kept in directory: {bot_dir}")
        else:
            logger.info("Cleaning up generated files")
            shutil.rmtree(bot_dir)

        result = {
            "prompt": prompt,
            "bot_name": bot_name,
            "messages": conversation_text,
            "rating": evaluation["rating"],
            "explanation": evaluation["explanation"],
            "thinking": evaluation["thinking"],
        }
        return result
        
    finally:
        tester.stop_bot(bot_dir)


DEFAULT_PROMPTS = (
     (
         "PlantBot",
         "hey can u make me a bot that tracks my plants and finds relevant info about? like when i water them and stuff... need it to remind me when to water next",
     ),
    #  (
    #      "ComicBot",
    #      "Generate a bot to manage my comic book collection - should track titles, issues, and value estimates. Thanks!",
    #  ),
     (
         "HomeworkBot",
         "need bot 4 tracking my kids homework assignments and searching if needed & due dates... must be simple 2 use!",
     ),
    #  (
    #      "WardrobeBot",
    #      "Can you create a bot that suggests outfit combinations from my wardrobe? I want to input my clothes and get daily suggestions",
    #  ),
    #  (
    #      "SpanishBot",
    #      "make me a bot that helps me practice spanish! should ask me random words daily and track my progress",
    #  ),
    #  (
    #      "GameBot",
    #      "Generate chatbot to manage my board game nights - need to track who's coming, which games we're bringing, and keep score",
    #  ),
    #  (
    #      "CoffeeBot",
    #      "I want a bot that tracks my coffee consumption and tells me fun facts about coffee everytime i log a cup!",
    #  ),
    #  (
    #      "RecipeBot",
    #      "create me a bot that keeps track of my favorite recipes and suggests what to cook based on ingredients i have at home",
    #  ),
    #  (
    #      "MedsBot",
    #      "Need simple bot that helps me track my medication schedule & reminds me when to take pills... thx!",
    #  ),
    #  (
    #      "MoodBot",
    #      "make me a bot that gives me daily positive affirmations and tracks my mood over time please :)",
    #  ),
 )

def eval_all_prompts(output_file: str = "results.json", messages: int = 10, keep_files: bool = True):
    pool = jl.Parallel(n_jobs=-1, backend="sequential" if os.getenv("DEBUG") else "loky")
    jobs = [jl.delayed(eval_single_prompt)(prompt, bot_name, messages, keep_files) for bot_name, prompt in DEFAULT_PROMPTS]
    results = pool(jobs)

    with open(output_file, "w") as fd:
        json.dump(results, fd, indent=4)
    return results



if __name__ == "__main__":
    Fire(eval_all_prompts)