from enum import Enum, auto
import os
from typing import TypedDict, Union, List
from pathlib import Path
import subprocess
import re
import json

class TypeSpecCompilationStatus(Enum):
    SUCCESS = auto()
    COMPILATION_ERROR = auto()
    UNKNOWN_ERROR = auto()
    
class CompilationResult(TypedDict):
    result: TypeSpecCompilationStatus
    errors: List[str]
    file_path: str
    stdout: str
    stderr: str

class TypeSpecCompiler:
    def __init__(self, cwd: Union[str, Path] = '.'):
        self.cwd = cwd
        self.error_pattern = re.compile(
            r'(?P<filepath>.+?):(?P<line>\d+):(?P<col>\d+)\s*-\s*(?P<msg>.+)'
        )

    def compile(self, file_path: Union[str, Path]) -> CompilationResult:
        try:
            file_path = Path(file_path)
            result = subprocess.run(
                ['tsp', 'compile', str(file_path)], 
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,
                env={**dict(os.environ), 'NO_COLOR': '1'}
            )

            error_output = result.stderr.decode() if result.stderr else result.stdout.decode()
            if result.returncode == 0 and 'error' not in error_output.lower():
                return CompilationResult(
                    result=TypeSpecCompilationStatus.SUCCESS,
                    errors=[],
                    file_path=str(file_path),
                    stdout=result.stdout.decode(),
                    stderr=result.stderr.decode()
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
                result=TypeSpecCompilationStatus.COMPILATION_ERROR,
                errors=errors or ["Unknown compilation error"],
                file_path=str(file_path),
                stdout=result.stdout.decode(),
                stderr=result.stderr.decode()
            )

        except subprocess.CalledProcessError as e:
            return CompilationResult(
                result=TypeSpecCompilationStatus.UNKNOWN_ERROR,
                errors=[f"Compilation error: {str(e)}"],
                file_path=str(file_path),
            )
        except Exception as e:
            return CompilationResult(
                result=TypeSpecCompilationStatus.UNKNOWN_ERROR,
                errors=[f"Unexpected error: {str(e)}"],
                file_path=str(file_path),
            )

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Please provide working directory ands path to TypeSpec file")
        sys.exit(1)
        
    compiler = TypeSpecCompiler(cwd=sys.argv[1])
    result = compiler.compile(file_path=sys.argv[2])
    print(result)