import os
import tempfile
import shutil
import unittest
from unittest.mock import MagicMock
from application import Application
from core.interpolator import Interpolator, CUSTOM_TOOL_TEMPLATE

class CustomToolsGenerationTest(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.test_dir, "output")
        
    def tearDown(self):
        shutil.rmtree(self.test_dir)
    
    def test_custom_tools_interpolation_directly(self):
        """Test that custom_tools.ts is generated correctly with pica handlers by directly testing the interpolator"""
        from core.datatypes import ApplicationOut, DrizzleOut, CapabilitiesOut, TypescriptOut, TypespecOut, HandlerOut, HandlerTestsOut, RefineOut, GherkinOut, LLMFunction
        
        # Create a test application with a pica_calendar handler
        app = ApplicationOut(
            drizzle=DrizzleOut(
                drizzle_schema="// Test drizzle schema",
                reasoning=None,
                error_output=None
            ),
            capabilities=CapabilitiesOut(
                capabilities=["pica.calendar"],
                error_output=None
            ),
            typescript_schema=TypescriptOut(
                typescript_schema="// Test typescript schema",
                reasoning=None,
                functions=None,
                error_output=None
            ),
            typespec=TypespecOut(
                typespec_definitions="// Test typespec definitions",
                llm_functions=[
                    LLMFunction(
                        name="pica.calendar",
                        description="Get user's calendar events",
                        scenario="User wants to get calendar events"
                    )
                ],
                reasoning=None,
                error_output=None
            ),
            handlers={
                "pica.calendar": HandlerOut(
                    handler="// Pica calendar handler code",
                    argument_schema="PicaCalendarSchema",
                    name="pica.calendar",
                    error_output=None
                ),
                "test_handler": HandlerOut(
                    handler="// Test handler code",
                    argument_schema="TestArgSchema",
                    name="test_handler",
                    error_output=None
                )
            },
            handler_tests={
                "pica.calendar": HandlerTestsOut(
                    content="// Test handler test",
                    name="pica.calendar",
                    error_output=None
                )
            },
            refined_description=RefineOut(
                refined_description="Test application with pica calendar",
                error_output=None
            ),
            gherkin=GherkinOut(
                gherkin=None,
                reasoning=None,
                error_output=None
            ),
            trace_id="test-trace-id"
        )
        
        # Create directory structure for templates
        app_schema_dir = os.path.join(self.test_dir, "templates", "app_schema", "src")
        os.makedirs(os.path.join(app_schema_dir, "db", "schema"), exist_ok=True)
        os.makedirs(os.path.join(app_schema_dir, "common"), exist_ok=True)
        os.makedirs(os.path.join(app_schema_dir, "handlers"), exist_ok=True)
        os.makedirs(os.path.join(app_schema_dir, "tests", "handlers"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "templates", "tsp_schema"), exist_ok=True)
        
        # Create interpolator and bake application
        interpolator = Interpolator(self.test_dir)
        interpolator.bake(app, self.output_dir)
        
        # Check if custom_tools.ts is generated
        custom_tools_path = os.path.join(self.output_dir, "app_schema", "src", "custom_tools.ts")
        self.assertTrue(os.path.exists(custom_tools_path), "custom_tools.ts not generated")
        
        with open(custom_tools_path, "r") as f:
            content = f.read()
        
        # Check if content contains signature elements from CUSTOM_TOOL_TEMPLATE
        self.assertIn("import type { CustomToolHandler }", content, 
                     "custom_tools.ts does not use CUSTOM_TOOL_TEMPLATE")
        self.assertIn("can_handle:", content, 
                     "custom_tools.ts does not include can_handle property")
        
        # Check if imports are generated correctly for pica
        self.assertIn("import * as pica from", content,
                    "Pica module import not generated correctly")
        
        # Check if handler name is included correctly with dot replaced by underscore
        self.assertIn("name: 'pica_calendar'", content,
                    "Handler name not included correctly")

if __name__ == "__main__":
    unittest.main()