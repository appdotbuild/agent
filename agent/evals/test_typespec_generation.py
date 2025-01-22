import os
import subprocess
import tempfile
from typing import Optional
from anthropic import AnthropicBedrock
from core import stages

def write_tsp_file(content: str, filepath: str) -> None:
    """Write TypeSpec content to a file."""
    with open(filepath, 'w') as f:
        f.write(content)

def compile_typespec(filepath: str) -> bool:
    """Compile TypeSpec file using tsp compiler."""
    try:
        # Run tsp compiler
        result = subprocess.run(
            ['tsp', 'compile', filepath],
            capture_output=True,
            text=True,
            check=False
        )
        return result.returncode == 0
    except subprocess.CalledProcessError:
        return False

def evaluate_typespec_generation() -> float:
    """
    Run TypeSpec generation 50 times and evaluate success rate.
    Returns percentage of successful compilations.
    """
    try:
        # Initialize AWS client
        client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")
    except Exception as e:
        print(f"Failed to initialize AWS client: {str(e)}")
        return 0.0
    
    # Test cases - variety of bot descriptions
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
    total_attempts = 50
    
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(total_attempts):
            # Use cycling test descriptions
            description = test_descriptions[i % len(test_descriptions)]
            
            try:
                # Generate TypeSpec
                prompt = stages.typespec.PROMPT.format(
                    application_description=description
                )
                
                print(f"\nAttempt {i + 1}/50:")
                print(f"Description: {description}")
                
                response = client.messages.create(
                    model="anthropic.claude-3-5-sonnet-20241022-v2:0",
                    max_tokens=8192,
                    messages=[{"role": "user", "content": prompt}]
                )
                
                # Parse output
                try:
                    result = stages.typespec.parse_output(response.content[0].text)
                    print("Successfully parsed LLM output")
                except Exception as e:
                    print(f"Failed to parse LLM output: {str(e)}")
                    continue
                    
                if result and result.get("typespec_definitions"):
                    # Write to temporary file
                    tsp_filepath = os.path.join(tmpdir, f'test_{i}.tsp')
                    write_tsp_file(result["typespec_definitions"], tsp_filepath)
                    print("TypeSpec content written to file")
                    
                    # Compile and check success
                    if compile_typespec(tsp_filepath):
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
