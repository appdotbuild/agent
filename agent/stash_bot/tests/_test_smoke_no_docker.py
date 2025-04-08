import sys
import os
import pytest
from unittest.mock import MagicMock, patch
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dagger
from dag_compiler import Compiler
from application import Application
from anthropic import AnthropicBedrock


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_application_no_docker():
    """
    Test Application by mocking the solve_agent function to avoid any LLM invocations.
    Verify the structure and types of the outputs.
    """
    from fsm_core.common import AgentState
    from fsm_core import typespec, drizzle, typescript, handler_tests, handlers
    from dag_compiler import CompileResult
    
    # Create actual instance objects from FSM core module for proper mocking
    def create_success_node(success_class, **kwargs):
        success = success_class(**kwargs)
        state = AgentState(inner=success, event=None)
        class NodeMock:
            data = state
        return NodeMock()
        
    # Create typespec success instance with the proper structure
    llm_func = typespec.LLMFunction(
        name="processInput",
        description="Process user input and generate response",
        scenario="Simple test scenario"
    )
    
    typespec_compile_result = CompileResult(
        exit_code=0,
        stdout="",
        stderr=""
    )
    
    typespec_node = create_success_node(
        typespec.Success,
        reasoning="Mocked reasoning",
        typespec="""
        model InputMessage {
            content: string;
        }

        model ResponseMessage {
            reply: string;
        }

        interface SimpleResponseBot {
            @scenario("Simple test scenario")
            @llm_func("process user input and generate response")
            processInput(options: InputMessage): ResponseMessage;
        }
        """,
        llm_functions=[llm_func],
        feedback=typespec_compile_result
    )
    
    # Create typescript function and success
    typescript_func = typescript.FunctionDeclaration(
        name="processInput",
        argument_type="InputMessage",
        argument_schema="z.object({content: z.string()})",
        return_type="ResponseMessage"
    )
    
    typescript_compile_result = CompileResult(
        exit_code=0,
        stdout="",
        stderr=""
    )
    
    type_to_zod = {
        "InputMessage": "inputMessageSchema",
        "ResponseMessage": "responseMessageSchema"
    }
    
    typescript_node = create_success_node(
        typescript.Success,
        reasoning="Mocked typescript reasoning",
        typescript_schema="""
        import { z } from 'zod';
        export const inputMessageSchema = z.object({
            content: z.string(),
        });
        export type InputMessage = z.infer<typeof inputMessageSchema>;
        """,
        functions=[typescript_func],
        type_to_zod=type_to_zod,
        feedback=typescript_compile_result
    )
    
    # Create drizzle success
    drizzle_compile_result = CompileResult(
        exit_code=0,
        stdout="",
        stderr=""
    )
    
    drizzle_node = create_success_node(
        drizzle.Success,
        reasoning="Mocked drizzle reasoning",
        drizzle_schema="""
        import { integer, pgTable, text } from "drizzle-orm/pg-core";
        export const messagesTable = pgTable("messages", {
          id: integer().primaryKey(),
          content: text().notNull(),
        });
        """,
        feedback=drizzle_compile_result
    )
    
    # Handler tests success
    handler_tests_compile_result = CompileResult(
        exit_code=0,
        stdout="",
        stderr=""
    )
    
    handler_tests_node = create_success_node(
        handler_tests.Success,
        function_name="processInput",
        typescript_schema=typescript_node.data.inner.typescript_schema,
        drizzle_schema=drizzle_node.data.inner.drizzle_schema,
        imports="""
        import { expect, it } from "bun:test";
        import { db } from "../../db";
        import { messagesTable } from "../../db/schema/application";
        import { eq } from "drizzle-orm";
        import type { InputMessage } from "../../common/schema";
        """,
        tests=["""
        it("should work", async () => {
          expect(true).toBe(true);
        });
        """],
        feedback=handler_tests_compile_result
    )
    
    # Handler success
    handlers_compile_result = CompileResult(
        exit_code=0,
        stdout="",
        stderr=""
    )
    
    handler_code = """
    export const handle = async (options) => {
      return { reply: `Received: ${options.content}` };
    };
    """
    
    handlers_node = create_success_node(
        handlers.Success,
        function_name="processInput",
        typescript_schema=typescript_node.data.inner.typescript_schema,
        drizzle_schema=drizzle_node.data.inner.drizzle_schema,
        source=handler_code,
        feedback=handlers_compile_result,
        test_suite=None,
        test_feedback=None
    )
    
    # Mock implementation of solve_agent
    def mock_solve_agent(init, context, m_claude, langfuse, trace_id, observation_id, max_depth=3, max_width=2):
        if isinstance(init, typespec.Entry):
            return typespec_node, None
        elif isinstance(init, drizzle.Entry):
            return drizzle_node, None
        elif isinstance(init, typescript.Entry):
            return typescript_node, None
        elif isinstance(init, handler_tests.Entry):
            return handler_tests_node, None
        elif isinstance(init, handlers.Entry):
            return handlers_node, None
        else:
            raise ValueError(f"Unexpected init type: {type(init)}")
    
    # Mock state machine to directly set context values without running the FSM
    class MockStateMachine:
        def __init__(self, root, context):
            self.root = root
            self.context = context
            self.stack_path = []
            
        # Support generic typing syntax
        def __class_getitem__(cls, item):
            return cls

        def send(self, event):
            from application import FsmState
            
            if event == "PROMPT":
                # Set the typespec data in context directly
                self.context["typespec_schema"] = typespec_node.data.inner
                self.stack_path = [FsmState.COMPLETE]
            elif event == "CONFIRM":
                # Set all the data in context directly for update_bot path
                self.context["typespec_schema"] = typespec_node.data.inner
                self.context["drizzle_schema"] = drizzle_node.data.inner
                self.context["typescript_schema"] = typescript_node.data.inner
                
                # Create a dict with the handler tests
                self.context["handler_tests"] = {"processInput": handler_tests_node.data.inner}
                
                # Create a dict with the handlers
                self.context["handlers"] = {"processInput": handlers_node.data.inner}
                
                self.stack_path = [FsmState.COMPLETE]
    
    # Mock Langfuse
    mock_langfuse = MagicMock()
    mock_langfuse.span.return_value.id = "mock-span-id"
    mock_langfuse.trace.return_value.id = "mock-trace-id"
    
    # Replace solve_agent with our mock and statemachine with our mock
    with patch('application.solve_agent', side_effect=mock_solve_agent):
        with patch('langfuse.Langfuse', return_value=mock_langfuse):
            with patch('statemachine.StateMachine', MockStateMachine):
                # Set up test
                async with dagger.connection(dagger.Config(log_output=sys.stderr)):
                    compiler = Compiler("./agent")
                    client = MagicMock(spec=AnthropicBedrock)
                    
                    # Create application and run test
                    application = Application(client, compiler)
                    
                    # Test prepare_bot with known trace IDs for predictable output
                    prepared_bot = await application.prepare_bot(
                        ["Create a test bot"], 
                        langfuse_observation_id="mock-trace-id"
                    )
                
                # Verify prepare_bot output
                assert prepared_bot.typespec is not None
                assert prepared_bot.typespec.typespec_definitions is not None
                assert prepared_bot.typespec.reasoning == "Mocked reasoning"
                assert "model InputMessage" in prepared_bot.typespec.typespec_definitions
                assert prepared_bot.typespec.error_output is None
                
                # Test update_bot - pass a properly formatted typespec that can be parsed
                test_typespec = """
                <reasoning>
                This is a simple chatbot with very basic logic.
                </reasoning>

                <typespec>
                model InputMessage {
                    content: string;
                }

                model ResponseMessage {
                    reply: string;
                }

                interface SimpleResponseBot {
                    @scenario(\"\"\"
                    Given a user input, the bot should generate a response
                    When the user input is a string, the bot should generate a response
                    When the user input is a number, the bot should generate a response
                    When the user input is a mixed input, the bot should generate a response
                    \"\"\")
                    @llm_func("process user input and generate response")
                    processInput(options: InputMessage): ResponseMessage;
                }
                </typespec>
                """
                async with dagger.connection(dagger.Config(log_output=sys.stderr)):
                    my_bot = await application.update_bot(
                        test_typespec,
                        langfuse_observation_id="mock-trace-id"
                    )
                
                # Verify update_bot output
                assert my_bot.typespec is not None
                assert my_bot.typespec.error_output is None
                
                assert my_bot.drizzle is not None
                assert my_bot.drizzle.error_output is None
                assert my_bot.drizzle.drizzle_schema is not None
                assert "messagesTable" in my_bot.drizzle.drizzle_schema
                
                assert my_bot.typescript_schema is not None
                assert my_bot.typescript_schema.error_output is None
                assert my_bot.typescript_schema.typescript_schema is not None
                assert "inputMessageSchema" in my_bot.typescript_schema.typescript_schema
                
                # Verify handler tests
                assert len(my_bot.handler_tests) == 1
                assert "processInput" in my_bot.handler_tests
                assert my_bot.handler_tests["processInput"].error_output is None
                assert "expect(true).toBe(true)" in my_bot.handler_tests["processInput"].content
                
                # Verify handlers
                assert len(my_bot.handlers) == 1
                assert "processInput" in my_bot.handlers
                assert my_bot.handlers["processInput"].error_output is None
                assert "return { reply: `Received: ${options.content}` }" in my_bot.handlers["processInput"].handler
                
                # Ensure trace_id is set
                assert my_bot.trace_id == "mock-trace-id"
