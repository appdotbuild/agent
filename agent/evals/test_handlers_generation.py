import os
import tempfile
import re
from typing import Dict
from anthropic import AnthropicBedrock
from compiler.core import Compiler
from policies import handlers
from application import Application

DATASET_DIR = "evals/dataset.min"
SCHEMA_SUFFIXES = {
    "_typescript_schema.ts": "typescript_schema",
    "_drizzle_schema.ts": "drizzle_schema",
    "_typespec_schema.tsp": "typespec_definitions"
}

def evaluate_handlers_generation() -> float:
    # Initialize core components
    try:
        client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")
        compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
    except Exception as e:
        print(f"Failed to initialize core components: {str(e)}")
        return 0.0

    # Load test data
    data_mapping = load_test_data()
    if not data_mapping:
        print("No test data found")
        return 0.0

    successful_compilations = 0
    total_attempts = 3

    with tempfile.TemporaryDirectory() as tmpdir:
        application = Application(client, compiler, "templates", tmpdir)

        for i in range(total_attempts):
            try:
                test_case = list(data_mapping.values())[i % len(data_mapping)]
                
                print(f"\nAttempt {i + 1}/{total_attempts}:")
                
                llm_functions = re.compile(r'@llm_func\(\d+\)\s*(\w+)\s*\(', re.DOTALL).findall(test_case["typespec_definitions"])
                handlers = application._make_handlers(
                    llm_functions,
                    test_case["typespec_definitions"],
                    test_case["typescript_schema"],
                    test_case["drizzle_schema"]
                )
                
                # Check compilation results
                all_handlers_compiled = True
                for name, handler in handlers.items():
                    if handler.error_output is not None:
                        print(f"Handler {name} compilation failed:")
                        print(handler.error_output)
                        all_handlers_compiled = False
                    else:
                        print(f"Handler {name} compilation successful")

                if all_handlers_compiled:
                    successful_compilations += 1

            except Exception as e:
                print(f"Error in iteration {i}: {str(e)}")
                continue

    success_rate = (successful_compilations / total_attempts) * 100
    print(f"\nHandlers Generation Success Rate: {success_rate:.2f}%")
    print(f"Successful compilations: {successful_compilations}/{total_attempts}")
    
    return success_rate

def load_test_data() -> Dict:
    """Load test schemas from dataset directory"""
    data_mapping = {}
    
    for filename in os.listdir(DATASET_DIR):
        for suffix, schema_key in SCHEMA_SUFFIXES.items():
            if filename.endswith(suffix):
                prefix = filename[:-len(suffix)]
                filepath = os.path.join(DATASET_DIR, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    data_mapping.setdefault(prefix, {})[schema_key] = f.read()
                break

    # Filter out incomplete test cases
    return {
        prefix: schemas 
        for prefix, schemas in data_mapping.items() 
        if all(key in schemas for key in SCHEMA_SUFFIXES.values())
    }

if __name__ == "__main__":
    evaluate_handlers_generation()
