import os
import tempfile
from typing import Dict
from anthropic import AnthropicBedrock
from compiler.core import Compiler
from fsm_core import drizzle
from application import Application
from tracing_client import TracingClient

DATASET_DIR = "evals/dataset.min"
SCHEMA_SUFFIXES = {
    "_app.tsp": "typespec_definitions",
    "_app.ts": "typescript_schema",
    "_db.ts": "drizzle_schema"
}

def evaluate_drizzle_generation() -> float:
    try:
        client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")
        compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
        tracing_client = TracingClient(client)
    except Exception as e:
        print(f"Failed to initialize core components: {str(e)}")
        return 0.0

    # Load test data
    data_mapping = load_test_data()
    if not data_mapping:
        print("No test data found")
        return 0.0

    successful_compilations = 0
    total_attempts = 10

    with tempfile.TemporaryDirectory() as tmpdir:
        application = Application(client, compiler)

        for i in range(total_attempts):
            try:
                test_case = list(data_mapping.values())[i % len(data_mapping)]
                
                print(f"\nTest case {i + 1}/{total_attempts}:")
         
                # Generate drizzle schema
                jinja_env = application.jinja_env
                content = jinja_env.from_string(drizzle.PROMPT).render(typespec_definitions=test_case["typespec_definitions"])
                message = {"role": "user", "content": content}

                response = tracing_client.call_anthropic(
                    max_tokens=8192,
                    messages=[message],
                )

                reasoning, drizzle_schema = drizzle.DrizzleMachine.parse_output(response.content[-1].text)
                #print(f"Drizzle schema generated:\n{drizzle_schema}")

                # Compile drizzle schema
                feedback = application.compiler.compile_drizzle(drizzle_schema)
                if feedback['exit_code'] == 0 and feedback['stderr'] is None:
                    print("Drizzle schema compilation successful")
                    successful_compilations += 1
                else:
                    print("Drizzle schema compilation failed - starting loop")
                    print(feedback['stderr'].split('\n')[-1])

                    result = application._make_drizzle(test_case["typespec_definitions"])
                    if result.error_output is not None:
                        print(result.error_output)
                    else:
                        successful_compilations += 1
                        print("Drizzle schema compilation successful")

            except Exception as e:
                    print(f"Error in iteration {i}: {str(e)}")
                    continue

    success_rate = (successful_compilations / total_attempts) * 100
    print(f"\nDrizzle Generation Success Rate: {success_rate:.2f}%")
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
    evaluate_drizzle_generation()
