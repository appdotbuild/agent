"""
Direct test for run_sequence that avoids relative import issues.
"""
import os
import sys

# Set up path for imports
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Import necessary modules
from compiler.core import Compiler
from anthropic import AnthropicBedrock
from langfuse import Langfuse
from functools import partial

# Import FSM modules with absolute paths
import fsm_core.common as common
import fsm_core.typespec as typespec
import fsm_core.drizzle as drizzle
import fsm_core.typescript as typescript
import fsm_core.handler_tests as handler_tests
import fsm_core.handlers as handlers

class Context:
    def __init__(self, compiler: Compiler):
        self.compiler = compiler

def run_sequence_direct():
    """Run the sequence directly using absolute imports"""
    langfuse_client = Langfuse()
    compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
    m_claude = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")
    
    # Import required functions from run_sequence
    # This approach bypasses the relative import issues in run_sequence.py
    from fsm_core.run_sequence import solve_agent
    
    solver = partial(solve_agent, m_claude=m_claude, langfuse=langfuse_client)

    print("Starting typespec generation...")
    tsp_start = typespec.Entry("Generate a bot that stores and searches notes")
    tsp_result, _tsp_root = solver(tsp_start, Context(compiler), "solve_typespec")
    assert tsp_result and isinstance(tsp_result.data.inner, typespec.Success), "typespec solution failed"
    print("TypeSpec generation successful")

    print("Starting drizzle generation...")
    dz_start = drizzle.Entry(tsp_result.data.inner.typespec)
    dz_result, _dz_root = solve_agent(dz_start, Context(compiler), "solve_drizzle", m_claude, langfuse_client)
    assert dz_result and isinstance(dz_result.data.inner, drizzle.Success), "drizzle solution failed"
    print("Drizzle generation successful")

    print("Starting typescript generation...")
    tsc_start = typescript.Entry(tsp_result.data.inner.typespec)
    tsc_result, _tsc_root = solve_agent(tsc_start, Context(compiler), "solve_typescript", m_claude, langfuse_client)
    assert tsc_result and isinstance(tsc_result.data.inner, typescript.Success), "typescript solution failed"
    print("TypeScript generation successful")

    print("Starting handler tests generation...")
    function = tsc_result.data.inner.functions[0]
    tests_start = handler_tests.Entry(function.name, tsc_result.data.inner.typescript_schema, dz_result.data.inner.drizzle_schema)
    tests_result, _tests_root = solve_agent(tests_start, Context(compiler), "solve_handler_tests", m_claude, langfuse_client)
    assert tests_result and isinstance(tests_result.data.inner, handler_tests.Success), "handler tests solution failed"
    print("Handler tests generation successful")

    print("Starting handler implementation generation...")
    function = tsc_result.data.inner.functions[0]
    handler_start = handlers.Entry(function.name, tsc_result.data.inner.typescript_schema, dz_result.data.inner.drizzle_schema, tests_result.data.inner.source)
    handler_result, _handler_root = solve_agent(handler_start, Context(compiler), "solve_handlers", m_claude, langfuse_client)
    assert handler_result and isinstance(handler_result.data.inner, handlers.Success), "handler solution failed"
    print("Handler implementation generation successful")
    
    print("All stages completed successfully!")
    return True

if __name__ == "__main__":
    run_sequence_direct()