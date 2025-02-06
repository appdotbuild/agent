import unittest
from unittest.mock import Mock, patch
from anthropic import AnthropicBedrock
from anthropic.types import ContentBlock, Message
from agent.compiler.core import Compiler
from agent.policies import typespec, typescript, drizzle, router, handlers
from agent.tracing_client import TracingClient

class MockAnthropicResponse:
    def __init__(self, content):
        self.content = [{
            "type": "text",
            "text": content
        }]

class MockToolResponse:
    def __init__(self, tool_outputs):
        self.content = [{
            "type": "tool_use",
            "name": "extract_user_functions",
            "input": {"user_functions": tool_outputs}
        }]

class TestPolicies(unittest.TestCase):
    def setUp(self):
        self.mock_client = Mock(spec=AnthropicBedrock)
        self.mock_client.messages = Mock()
        self.mock_client.messages.create = Mock()
        self.mock_compiler = Mock(spec=Compiler)
        self.tracing_client = TracingClient(self.mock_client)

    def test_typespec_task_node(self):
        mock_response = """
        <reasoning>
        Test reasoning for typespec
        </reasoning>
        <typespec>
        model TestModel {
            id: string;
            value: integer;
        }
        
        interface TestInterface {
            @llm_func(1)
            testFunction(model: TestModel): void;
        }
        </typespec>
        """
        
        # Mock successful compilation
        self.mock_compiler.compile_typespec.return_value = {
            "exit_code": 0,
            "stdout": None,
            "stderr": None
        }
        
        # Mock LLM response
        self.mock_client.messages.create.return_value = MockAnthropicResponse(mock_response)
        
        with typespec.TypespecTaskNode.platform(self.tracing_client, self.mock_compiler, Mock()):
            result = typespec.TypespecTaskNode.run([{"role": "user", "content": "test"}])
            
        self.assertIsInstance(result, typespec.TypespecData)
        self.assertIsInstance(result.output, typespec.TypespecOutput)
        self.assertEqual(result.output.llm_functions, ["testFunction"])
        self.assertIn("TestModel", result.output.typespec_definitions)

    def test_typescript_task_node(self):
        mock_response = """
        <reasoning>
        Test reasoning for typescript
        </reasoning>
        <typescript>
        export interface TestInterface {
            id: string;
            value: number;
        }
        </typescript>
        """
        
        # Mock successful compilation
        self.mock_compiler.compile_typescript.return_value = {
            "exit_code": 0,
            "stdout": None,
            "stderr": None
        }
        
        # Mock LLM response
        self.mock_client.messages.create.return_value = MockAnthropicResponse(mock_response)
        
        with typescript.TypescriptTaskNode.platform(self.tracing_client, self.mock_compiler, Mock()):
            result = typescript.TypescriptTaskNode.run([{"role": "user", "content": "test"}])
            
        self.assertIsInstance(result, typescript.TypescriptData)
        self.assertIsInstance(result.output, typescript.TypescriptOutput)
        self.assertEqual(result.output.type_names, ["TestInterface"])

    def test_drizzle_task_node(self):
        mock_response = """
        <reasoning>
        Test reasoning for drizzle
        </reasoning>
        <drizzle>
        import { pgTable, text, integer } from 'drizzle-orm/pg-core';
        
        export const testTable = pgTable('test', {
            id: text('id').primaryKey(),
            value: integer('value')
        });
        </drizzle>
        """
        
        # Mock successful compilation
        self.mock_compiler.compile_drizzle.return_value = {
            "exit_code": 0,
            "stdout": None,
            "stderr": None
        }
        
        # Mock LLM response
        self.mock_client.messages.create.return_value = MockAnthropicResponse(mock_response)
        
        with drizzle.DrizzleTaskNode.platform(self.tracing_client, self.mock_compiler, Mock()):
            result = drizzle.DrizzleTaskNode.run([{"role": "user", "content": "test"}])
            
        self.assertIsInstance(result, drizzle.DrizzleData)
        self.assertIsInstance(result.output, drizzle.DrizzleOutput)
        self.assertIn("testTable", result.output.drizzle_schema)

    def test_router_task_node(self):
        mock_functions = [
            {
                "name": "testFunction",
                "description": "Test function description",
                "examples": ["example1", "example2"]
            }
        ]
        
        # Mock LLM response with tool output
        self.mock_client.messages.create.return_value = MockToolResponse(mock_functions)
        
        with router.RouterTaskNode.platform(self.tracing_client, Mock()):
            result = router.RouterTaskNode.run([{"role": "user", "content": "test"}])
            
        self.assertIsInstance(result, router.RouterData)
        self.assertIsInstance(result.output, router.RouterOutput)
        self.assertEqual(len(result.output.functions), 1)
        self.assertEqual(result.output.functions[0]["name"], "testFunction")

    def test_handler_task_node(self):
        mock_response = """
        <handler>
        export async function testHandler(input: TestInput): Promise<void> {
            // Test handler implementation
            console.log(input);
        }
        </handler>
        """
        
        # Mock successful compilation
        self.mock_compiler.compile_typescript.return_value = {
            "exit_code": 0,
            "stdout": None,
            "stderr": None
        }
        
        # Mock LLM response
        self.mock_client.messages.create.return_value = MockAnthropicResponse(mock_response)
        
        with handlers.HandlerTaskNode.platform(self.tracing_client, self.mock_compiler, Mock()):
            result = handlers.HandlerTaskNode.run(
                [{"role": "user", "content": "test"}],
                function_name="testHandler",
                typescript_schema="interface TestInput {}",
                drizzle_schema="const testTable = pgTable('test', {});"
            )
            
        self.assertIsInstance(result, handlers.HandlerData)
        self.assertIsInstance(result.output, handlers.HandlerOutput)
        self.assertIn("testHandler", result.output.handler)

    def test_error_handling(self):
        # Test compilation error handling
        mock_response = """
        <reasoning>Test</reasoning>
        <typespec>invalid typespec code</typespec>
        """
        
        # Mock failed compilation
        self.mock_compiler.compile_typespec.return_value = {
            "exit_code": 1,
            "stdout": "Compilation error",
            "stderr": None
        }
        
        # Mock LLM response
        self.mock_client.messages.create.return_value = MockAnthropicResponse(mock_response)
        
        with typespec.TypespecTaskNode.platform(self.tracing_client, self.mock_compiler, Mock()):
            result = typespec.TypespecTaskNode.run([{"role": "user", "content": "test"}])
            
        self.assertIsInstance(result, typespec.TypespecData)
        self.assertIsInstance(result.output, typespec.TypespecOutput)
        self.assertEqual(result.output.feedback["exit_code"], 1)

if __name__ == '__main__':
    unittest.main() 