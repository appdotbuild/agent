from typing import TypedDict, Union, List
from pathlib import Path
import subprocess
import re
import json

class CompilationResult(TypedDict):
    success: bool
    errors: List[str]
    file_path: str

class TypeSpecCompiler:
    def __init__(self, tsp_path: str = '/usr/local/bin/tsp'):
        self.tsp_path = tsp_path
        self.error_pattern = re.compile(
            r'(?P<filepath>.+?):(?P<line>\d+):(?P<col>\d+)\s*-\s*(?P<msg>.+)'
        )

    def compile(self, file_path: Union[str, Path]) -> CompilationResult:
        file_path = Path(file_path)
        if not file_path.exists():
            return CompilationResult(
                success=False,
                errors=[f"File not found: {file_path}"],
                file_path=str(file_path)
            )

        try:
            result = subprocess.run(
                [self.tsp_path, 'compile', str(file_path)],
                capture_output=True,
                text=True,
                env={'NO_COLOR': '1'}
            )

            error_output = result.stderr if result.stderr else result.stdout
            if result.returncode == 0 and 'error' not in error_output.lower():
                return CompilationResult(
                    success=True,
                    errors=[],
                    file_path=str(file_path)
                )

            errors = []
            lines = error_output.split('\n')
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if not line:
                    i += 1
                    continue

                match = self.error_pattern.match(line)
                if match:
                    error = f"{match['line']}:{match['col']} - {match['msg']}"
                    
                    # Include context if available in next line
                    if i + 1 < len(lines) and lines[i + 1].startswith('>'):
                        error += f"\n{lines[i + 1].strip()}"
                        i += 1
                    
                    errors.append(error)
                elif 'error' in line.lower():
                    errors.append(line)
                
                i += 1

            return CompilationResult(
                success=False,
                errors=errors or ["Unknown compilation error"],
                file_path=str(file_path)
            )

        except subprocess.CalledProcessError as e:
            return CompilationResult(
                success=False,
                errors=[f"Compilation error: {str(e)}"],
                file_path=str(file_path)
            )
        except Exception as e:
            return CompilationResult(
                success=False,
                errors=[f"Unexpected error: {str(e)}"],
                file_path=str(file_path)
            )

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Please provide path to TypeSpec file")
        sys.exit(1)
        
    compiler = TypeSpecCompiler()
    result = compiler.compile(sys.argv[1])
    print(json.dumps(result, indent=2))