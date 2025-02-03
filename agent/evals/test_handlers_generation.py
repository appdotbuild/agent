import os
import subprocess
import tempfile
import jinja2
from typing import Optional
from anthropic import AnthropicBedrock
from core import stages
from compiler.core import Compiler

DATASET_DIR = "agent/evals/dataset.min"
SCHEMA_SUFFIXES = {
    "_typescript_schema.ts": "typescript_schema",
    "_drizzle_schema.ts": "drizzle_schema" 
}

def write_tsc_file(content: str, filepath: str) -> None:
    with open(filepath, 'w') as f:
        f.write(content)

def compile_typescript(filepath: str) -> bool:
    """Compile TypeSpec file using tsp compiler."""
    try:
        result = subprocess.run(
            ['npx', 'tsc', filepath],
            capture_output=True,
            text=True,
            check=False
        )
        return result.returncode == 0
    except subprocess.CalledProcessError:
        return False

def evaluate_handlers_generation() -> float:
    jinja_env = jinja2.Environment()
    handlers_tpl = jinja_env.from_string(stages.handlers.PROMPT)
    compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
    try:
        client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")
    except Exception as e:
        print(f"Failed to initialize AWS client: {str(e)}")
        return 0.0

    data_mapping = {}
    for filename in os.listdir(DATASET_DIR):
        for suffix, schema_key in SCHEMA_SUFFIXES.items():
            if filename.endswith(suffix):
                prefix = filename[:-len(suffix)]
                filepath = os.path.join(DATASET_DIR, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    data_mapping.setdefault(prefix, {})[schema_key] = f.read()
                break

    test_cases = [
        {
            "function_name": prefix,
            "typescript_schema": schemas["typescript_schema"], 
            "drizzle_schema": schemas["drizzle_schema"]
        }
        for prefix, schemas in data_mapping.items()
        if all(key in schemas for key in SCHEMA_SUFFIXES.values())
    ]
    
    successful_compilations = 0
    total_attempts = 5
    
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(total_attempts):
            test_case = test_cases[i % len(test_cases)]
            tsc_handler_file = f"{tmpdir}/{test_case['function_name']}.ts"
            try:
                prompt = handlers_tpl.render(function_name=test_case["function_name"], typescript_schema=test_case["typescript_schema"], drizzle_schema=test_case["drizzle_schema"])
                
                print(f"\nAttempt {i + 1}/{total_attempts}:")
                print(f"Test handler: {tsc_handler_file}")
                
                response = client.messages.create(
                    model="anthropic.claude-3-5-sonnet-20241022-v2:0",
                    max_tokens=8192,
                    messages=[{"role": "user", "content": prompt}]
                )
                
                try:
                    result = stages.handlers.parse_output(response.content[0].text)
                    print("Successfully parsed LLM output")
                except Exception as e:
                    print(f"Failed to parse LLM output: {str(e)}")
                    continue
                    
                if result and result.get("handler"):
                    result = compiler.compile_typescript({f"{tsc_handler_file}": result["handler"]})
                    
                    if result["exit_code"] == 0:
                        successful_compilations += 1
                        print("TypeSpec compilation successful")
                    else:
                        print("TypeSpec compilation failed")
                else:
                    print("No TypeSpec definitions found in result")
            
            except Exception as e:
                print(f"Error in iteration {i}: {str(e)}")
                continue
    
    success_rate = (successful_compilations / total_attempts) * 100
    print(f"\nHandlers Generation Success Rate: {success_rate:.2f}%")
    print(f"Successful compilations: {successful_compilations}/{total_attempts}")
    
    return success_rate

if __name__ == "__main__":
    evaluate_handlers_generation()
