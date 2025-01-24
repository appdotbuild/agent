from typing import TypedDict
from enum import Enum, auto


class CompilationStatus(Enum):
    SUCCESS = auto()
    FAILURE = auto()


class CompilationResult(TypedDict):
    result: CompilationStatus
    errors: str | None
    stdout: str | None
