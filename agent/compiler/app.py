from typing import Optional
from fastapi import FastAPI
from pydantic import BaseModel
from core import Compiler
from settings import settings

app = FastAPI()
compiler = Compiler(settings.TSP_IMAGE, settings.APP_IMAGE)


class CompileResult(BaseModel):
    exit_code: int
    stdout: Optional[str]
    stderr: Optional[str]


class CompileDrizzleRequest(BaseModel):
    payload: str


@app.post("/compile/drizzle", response_model=CompileResult)
def compile_drizzle(request: CompileDrizzleRequest):
    return compiler.compile_drizzle(request.payload)


class CompileTypespecRequest(BaseModel):
    payload: str


@app.post("/compile/typespec", response_model=CompileResult)
def compile_typespec(request: CompileTypespecRequest):
    return compiler.compile_typespec(request.payload)

class CompileTypescriptRequest(BaseModel):
    payload: dict[str, str]


@app.post("/compile/typescript", response_model=CompileResult)
def compile_typescript(request: CompileTypescriptRequest):
    return compiler.compile_typescript(request.payload)
