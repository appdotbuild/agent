import unittest
from unittest.mock import Mock, patch, MagicMock
from anthropic import AnthropicBedrock
from anthropic.types import ContentBlock
from ..application import Application, TypespecOut, DrizzleOut, RouterOut, HandlerOut, TypescriptOut
from compiler.core import Compiler

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

class TestApplication(unittest.TestCase):
    def setUp(self):
        self.mock_client = Mock(spec=AnthropicBedrock)
        self.mock_compiler = Mock(spec=Compiler)
        self.app = Application(
            client=self.mock_client,
            compiler=self.mock_compiler,
            template_dir="templates",
            output_dir="test_output"
        )

    @patch('agent.policies.typespec.TypespecTaskNode.run')
    def test_make_typespec(self, mock_typespec_run):
        # Mock successful typespec generation
        mock_typespec_run.return_value = MagicMock(
            data=MagicMock(
                output=MagicMock(
                    reasoning="Test reasoning",
                    typespec_definitions="""
                    model TestModel {
                        id: string;
                        value: integer;
                    }
                    interface TestInterface {
                        @llm_func(1)
                        testFunction(model: TestModel): void;
                    }
                    """,
                    llm_functions=["testFunction"],
                    error_or_none=None
                )
            )
        )

        result = self.app._make_typespec("Create a test application")
        
        self.assertIsInstance(result, TypespecOut)
        self.assertEqual(result.llm_functions, ["testFunction"])
        self.assertIsNone(result.error_output)
        mock_typespec_run.assert_called_once()

    @patch('agent.policies.typescript.TypescriptTaskNode.run')
    def test_make_typescript_schema(self, mock_typescript_run):
        # Mock successful typescript schema generation
        mock_typescript_run.return_value = MagicMock(
            data=MagicMock(
                output=MagicMock(
                    reasoning="Test reasoning",
                    typescript_schema="""
                    export interface TestInterface {
                        id: string;
                        value: number;
                    }
                    """,
                    type_names=["TestInterface"],
                    error_or_none=None
                )
            )
        )

        result = self.app._make_typescript_schema("type TestType = string;")
        
        self.assertIsInstance(result, TypescriptOut)
        self.assertEqual(result.type_names, ["TestInterface"])
        self.assertIsNone(result.error_output)
        mock_typescript_run.assert_called_once()

    @patch('agent.policies.drizzle.DrizzleTaskNode.run')
    def test_make_drizzle(self, mock_drizzle_run):
        # Mock successful drizzle schema generation
        mock_drizzle_run.return_value = MagicMock(
            data=MagicMock(
                output=MagicMock(
                    reasoning="Test reasoning",
                    drizzle_schema="""
                    import { pgTable, text, integer } from 'drizzle-orm/pg-core';
                    export const testTable = pgTable('test', {
                        id: text('id').primaryKey(),
                        value: integer('value')
                    });
                    """,
                    error_or_none=None
                )
            )
        )

        result = self.app._make_drizzle("type TestType = string;")
        
        self.assertIsInstance(result, DrizzleOut)
        self.assertIn("testTable", result.drizzle_schema)
        self.assertIsNone(result.error_output)
        mock_drizzle_run.assert_called_once()

    @patch('agent.policies.router.RouterTaskNode.run')
    def test_make_router(self, mock_router_run):
        # Mock successful router generation
        mock_router_run.return_value = MagicMock(
            data=MagicMock(
                output=MagicMock(
                    functions=[{
                        "name": "testFunction",
                        "description": "Test function",
                        "examples": ["example1", "example2"]
                    }],
                    error_output=None
                )
            )
        )

        result = self.app._make_router("type TestType = string;")
        
        self.assertIsInstance(result, RouterOut)
        self.assertEqual(len(result.functions), 1)
        self.assertEqual(result.functions[0]["name"], "testFunction")
        self.assertIsNone(result.error_output)
        mock_router_run.assert_called_once()

    @patch('agent.policies.handlers.HandlerTaskNode.run')
    def test_make_handlers(self, mock_handler_run):
        # Mock successful handler generation
        mock_handler_run.return_value = MagicMock(
            data=MagicMock(
                output=MagicMock(
                    handler="""
                    export async function testHandler(input: TestInput): Promise<void> {
                        console.log(input);
                    }
                    """,
                    error_output=None
                )
            )
        )

        result = self.app._make_handlers(
            llm_functions=["testFunction"],
            typespec_definitions="type TestType = string;",
            typescript_schema="interface TestInput {}",
            drizzle_schema="const testTable = pgTable('test', {});"
        )
        
        self.assertIsInstance(result, dict)
        self.assertIn("testFunction", result)
        self.assertIsInstance(result["testFunction"], HandlerOut)
        self.assertIn("testHandler", result["testFunction"].handler)
        self.assertIsNone(result["testFunction"].error_output)
        mock_handler_run.assert_called_once()

    @patch('agent.application.Application._make_typespec')
    @patch('agent.application.Application._make_typescript_schema')
    @patch('agent.application.Application._make_drizzle')
    @patch('agent.application.Application._make_router')
    @patch('agent.application.Application._make_handlers')
    def test_create_bot_success(
        self,
        mock_handlers,
        mock_router,
        mock_drizzle,
        mock_typescript,
        mock_typespec
    ):
        # Mock successful responses for all components
        mock_typespec.return_value = TypespecOut(
            reasoning="Test reasoning",
            typespec_definitions="type TestType = string;",
            llm_functions=["testFunction"],
            error_output=None
        )
        
        mock_typescript.return_value = TypescriptOut(
            reasoning="Test reasoning",
            typescript_schema="interface TestInterface {}",
            type_names=["TestInterface"],
            error_output=None
        )
        
        mock_drizzle.return_value = DrizzleOut(
            reasoning="Test reasoning",
            drizzle_schema="const testTable = pgTable('test', {});",
            error_output=None
        )
        
        mock_router.return_value = RouterOut(
            functions=[{
                "name": "testFunction",
                "description": "Test function",
                "examples": ["example1"]
            }],
            error_output=None
        )
        
        mock_handlers.return_value = {
            "testFunction": HandlerOut(
                handler="export function testHandler() {}",
                error_output=None
            )
        }

        result = self.app.create_bot("Create a test application")

        # Verify all components were called
        mock_typespec.assert_called_once()
        mock_typescript.assert_called_once()
        mock_drizzle.assert_called_once()
        mock_router.assert_called_once()
        mock_handlers.assert_called_once()

        # Verify the result structure
        self.assertIsNotNone(result)
        self.assertIsInstance(result.typespec, TypespecOut)
        self.assertIsInstance(result.typescript_schema, TypescriptOut)
        self.assertIsInstance(result.drizzle, DrizzleOut)
        self.assertIsInstance(result.router, RouterOut)
        self.assertIsInstance(result.handlers, dict)

    def test_create_bot_typespec_error(self):
        # Test error handling when typespec generation fails
        with patch('agent.application.Application._make_typespec') as mock_typespec:
            mock_typespec.return_value = TypespecOut(
                reasoning=None,
                typespec_definitions=None,
                llm_functions=None,
                error_output="TypeSpec compilation failed"
            )

            with self.assertRaises(Exception) as context:
                self.app.create_bot("Create a test application")

            self.assertIn("Failed to generate typespec", str(context.exception))

    def test_create_bot_with_bot_id(self):
        # Test bot creation with a specific bot_id
        with patch('agent.application.Application._make_typespec') as mock_typespec:
            mock_typespec.return_value = TypespecOut(
                reasoning="Test reasoning",
                typespec_definitions="type TestType = string;",
                llm_functions=["testFunction"],
                error_output=None
            )
            
            # Mock other necessary components
            with patch.multiple(
                'agent.application.Application',
                _make_typescript_schema=Mock(return_value=TypescriptOut(
                    reasoning="Test",
                    typescript_schema="interface Test {}",
                    type_names=["Test"],
                    error_output=None
                )),
                _make_drizzle=Mock(return_value=DrizzleOut(
                    reasoning="Test",
                    drizzle_schema="const test = pgTable();",
                    error_output=None
                )),
                _make_router=Mock(return_value=RouterOut(
                    functions=[{"name": "test", "description": "test", "examples": []}],
                    error_output=None
                )),
                _make_handlers=Mock(return_value={
                    "testFunction": HandlerOut(
                        handler="export function test() {}",
                        error_output=None
                    )
                })
            ):
                result = self.app.create_bot("Create a test application", bot_id="test-bot-123")
                
                self.assertIsNotNone(result)
                # Additional assertions could be added here to verify bot_id handling

if __name__ == '__main__':
    unittest.main() 