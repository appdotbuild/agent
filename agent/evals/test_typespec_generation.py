import tempfile
from anthropic import AnthropicBedrock
import jinja2
from compiler.core import Compiler
from core import stages

def write_tsp_file(content: str, filepath: str) -> None:
    """Write TypeSpec content to a file."""
    with open(filepath, 'w') as f:
        f.write(content)

def evaluate_typespec_generation() -> float:
    """
    Run TypeSpec generation 50 times and evaluate success rate.
    Returns percentage of successful compilations.
    """
    jinja_env = jinja2.Environment()
    typespec_tpl = jinja_env.from_string(stages.typespec.PROMPT)
    compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
    try:
        client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")
    except Exception as e:
        print(f"Failed to initialize AWS client: {str(e)}")
        return 0.0
    
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
    
    successful_compilations = 0
    total_attempts = 5
    
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(total_attempts):
            description = test_descriptions[i % len(test_descriptions)]
            try:
                # Generate TypeSpec
                prompt = typespec_tpl.render(application_description=description)
                
                print(f"\nAttempt {i + 1}/{total_attempts}:")
                print(f"Description: {description}")
                
                response = client.messages.create(
                    model="anthropic.claude-3-5-sonnet-20241022-v2:0",
                    max_tokens=8192,
                    messages=[{"role": "user", "content": prompt}]
                )
                
                try:
                    result = stages.typespec.parse_output(response.content[0].text)
                    print("Successfully parsed LLM output")
                except Exception as e:
                    print(f"Failed to parse LLM output: {str(e)}")
                    continue
                    
                if result and result.get("typespec_definitions"):
                    result = compiler.compile_typespec("\n".join([
                        'import "./helpers.js";',
                        ''
                        'extern dec llm_func(target: unknown, history: valueof int32);',
                        '',
                        result["typespec_definitions"]
                    ]))
                    
                    # Compile and check success
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
    print(f"\nTypeSpec Generation Success Rate: {success_rate:.2f}%")
    print(f"Successful compilations: {successful_compilations}/{total_attempts}")
    
    return success_rate

if __name__ == "__main__":
    evaluate_typespec_generation()
