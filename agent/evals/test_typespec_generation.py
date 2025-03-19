import os
import tempfile
from typing import Dict, Tuple
from anthropic import AnthropicBedrock
from tracing_client import TracingClient
from compiler.core import Compiler
from policies import typespec
from application3 import Application3

DATASET_DIR = "evals/dataset.min"
SCHEMA_SUFFIXES = {
    "_app.tsp": "typespec_definitions",
    "_app.ts": "typescript_schema", 
    "_db.ts": "drizzle_schema"
}

def evaluate_typespec_generation() -> float:
    """
    Run TypeSpec generation and evaluate success rate.
    Returns percentage of successful compilations.
    """
    try:
        client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")
        compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
        tracing_client = TracingClient(client)
    except Exception as e:
        print(f"Failed to initialize core components: {str(e)}")
        return 0.0

    successful_compilations = 0
    total_attempts = 10

    test_descriptions = [
        "A bot that manages personal finances and tracks expenses",
        "Chat bot for answering programming questions with code examples",
        "A recipe management bot that suggests meals and tracks ingredients",
        "Customer support bot for handling common product queries",
        "A language learning bot that helps practice conversations",
        "Task management bot for organizing project deadlines",
        "A fitness tracking bot for workout routines and progress",
        "Music recommendation bot based on user preferences",
        "Weather advisory bot with local forecasts and alerts",
        "A study assistant bot for organizing notes and schedules"
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        application = Application(client, compiler, "templates", tmpdir, branch_factor=1, max_depth=1, max_workers=1)

        for i in range(total_attempts):
            try:
                description = test_descriptions[i % len(test_descriptions)]
                
                print(f"\nTest case {i + 1}/{total_attempts}:")
                print(f"Description: {description}")

                # Generate TypeSpec
                jinja_env = application.jinja_env
                content = jinja_env.from_string(typespec.PROMPT).render(application_description=description)
                message = {"role": "user", "content": content}

                response = tracing_client.call_anthropic(
                    max_tokens=8192,
                    messages=[message],
                )

                reasoning, typespec_definitions, functions = typespec.TypespecTaskNode.parse_output(response.content[-1].text)
                
                typespec_schema = "\n".join(['import "./helpers.js";', "", typespec_definitions])
                feedback = application.compiler.compile_typespec(typespec_schema)
                if feedback['exit_code'] == 0 and feedback['stderr'] is None:
                    print("TypeSpec compilation attempt 1 successful")
                    successful_compilations += 1
                else:
                    print("TypeSpec compilation attempt 1 failed - running loop")
                    print(feedback['stdout'].split('\n')[-1])
                    result = application._make_typespec(description)
                    if result.error_output is None:
                        print("TypeSpec compilation loop successful")
                        successful_compilations += 1
                    else:
                        print("TypeSpec compilation failed")
    
            except Exception as e:
                print(f"Error in iteration {i}: {str(e)}")
                continue

    success_rate = (successful_compilations / total_attempts) * 100
    print(f"\nTypeSpec Generation Success Rate: {success_rate:.2f}%")
    print(f"Successful compilations: {successful_compilations}/{total_attempts}")
    
    return success_rate

if __name__ == "__main__":
    evaluate_typespec_generation()
