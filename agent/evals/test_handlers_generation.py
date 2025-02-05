import os
import tempfile
import jinja2
import re
from typing import Optional
from anthropic import AnthropicBedrock
from core import stages
from compiler.core import Compiler
from policies import handlers

DATASET_DIR = "evals/dataset.min"
SCHEMA_SUFFIXES = {
    "_typescript_schema.ts": "typescript_schema",
    "_drizzle_schema.ts": "drizzle_schema" 
}

def write_tsc_file(content: str, filepath: str) -> None:
    with open(filepath, 'w') as f:
        f.write(content)

def evaluate_handlers_generation() -> float:
    jinja_env = jinja2.Environment()
    handlers_tpl = jinja_env.from_string(handlers.PROMPT)
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

    test_cases = []
    for prefix, schemas in data_mapping.items():
        if not all(key in schemas for key in SCHEMA_SUFFIXES.values()):
            print(f"Skipping {prefix} because it is missing one or more required schemas")
            continue
        #print(schemas["typescript_schema"])
        function_names = re.findall(r'\b(\w+)\s*\(', schemas["typescript_schema"])
        for function_name in function_names:
            test_cases.append({
                "function_name": function_name,
                "typescript_schema": schemas["typescript_schema"], 
                "drizzle_schema": schemas["drizzle_schema"]
            })
    
    successful_compilations = 0
    total_attempts = 3
    delete_tmpdir = False
    
    with tempfile.TemporaryDirectory(delete=delete_tmpdir) as tmpdir:
        for i in range(total_attempts):
            test_case = test_cases[i % len(test_cases)]
            
            handlers_dir = "src/handlers"
            db_schema_dir = "src/db/schema"
            common_dir = "src/common"

            if not delete_tmpdir:
                os.makedirs(os.path.join(tmpdir, handlers_dir), exist_ok=True)
                os.makedirs(os.path.join(tmpdir, db_schema_dir), exist_ok=True)
                os.makedirs(os.path.join(tmpdir, common_dir), exist_ok=True)
            
            tsc_handler_file = os.path.join(handlers_dir, f"{test_case['function_name']}_{i}.ts")
            typescript_schema_file = os.path.join(common_dir, "schema.ts")
            drizzle_schema_file = os.path.join(db_schema_dir, "application.ts")
            
            try:
                prompt = handlers_tpl.render(function_name=test_case["function_name"],
                                             typescript_schema=test_case["typescript_schema"], 
                                             drizzle_schema=test_case["drizzle_schema"])
                
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
                    
                    #print(result["handler"])
                    
                    if not delete_tmpdir:
                        print(f"Writing handler to file {os.path.join(tmpdir, tsc_handler_file)}")
                        write_tsc_file(result["handler"], os.path.join(tmpdir, tsc_handler_file))
                        write_tsc_file(test_case["typescript_schema"], os.path.join(tmpdir, typescript_schema_file))
                        write_tsc_file(test_case["drizzle_schema"], os.path.join(tmpdir, drizzle_schema_file))
                    
                    feedback = compiler.compile_typescript({tsc_handler_file: result["handler"], 
                                                            typescript_schema_file: test_case["typescript_schema"], 
                                                            drizzle_schema_file: test_case["drizzle_schema"]})
                        
                    print(f"Compilation result: {feedback}")
                    
                    if feedback["exit_code"] == 0 and feedback["stderr"] is None:
                        successful_compilations += 1
                        print("Handler compilation successful")
                    else:
                        print(f"Handler compilation failed: {feedback['stderr']}")
                else:
                    print("No Handler found in result")
            
            except Exception as e:
                print(f"Error in iteration {i}: {str(e)}")
                continue
        
    success_rate = (successful_compilations / total_attempts) * 100
    print(f"\nHandlers Generation Success Rate: {success_rate:.2f}%")
    print(f"Successful compilations: {successful_compilations}/{total_attempts}")
    
    return success_rate

if __name__ == "__main__":
    evaluate_handlers_generation()
