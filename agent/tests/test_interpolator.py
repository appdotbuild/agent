import os
import tempfile
import shutil
import unittest
from core.interpolator import Interpolator, TOOL_TEMPLATE, CUSTOM_TOOL_TEMPLATE
from core.datatypes import ApplicationOut, DrizzleOut, TypescriptOut, TypespecOut, HandlerOut, HandlerTestsOut, RefineOut, GherkinOut

class InterpolatorTest(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.template_dir = os.path.join(self.test_dir, "templates")
        self.app_schema_dir = os.path.join(self.template_dir, "app_schema", "src")
        self.tsp_schema_dir = os.path.join(self.template_dir, "tsp_schema")
        
        # Create directory structure
        os.makedirs(os.path.join(self.app_schema_dir, "db", "schema"), exist_ok=True)
        os.makedirs(os.path.join(self.app_schema_dir, "common"), exist_ok=True)
        os.makedirs(os.path.join(self.app_schema_dir, "handlers"), exist_ok=True)
        os.makedirs(os.path.join(self.app_schema_dir, "tests", "handlers"), exist_ok=True)
        os.makedirs(self.tsp_schema_dir, exist_ok=True)
        
        self.output_dir = os.path.join(self.test_dir, "output")
        
    def tearDown(self):
        shutil.rmtree(self.test_dir)
    
    def test_custom_tools_interpolation(self):
        """Test that custom_tools.ts is generated with the CUSTOM_TOOL_TEMPLATE"""
        # Create test application
        app = ApplicationOut(
            drizzle=DrizzleOut(
                drizzle_schema="// Test drizzle schema",
                reasoning=None,
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
                llm_functions=[],
                reasoning=None,
                error_output=None
            ),
            handlers={
                "test_handler": HandlerOut(
                    handler="// Test handler code",
                    argument_schema="TestArgSchema",
                    name="test_handler",
                    error_output=None
                ),
                "pica_calendar": HandlerOut(
                    handler="// Pica calendar handler",
                    argument_schema="PicaCalendarSchema",
                    name="pica_calendar",
                    error_output=None
                )
            },
            handler_tests={
                "test_handler": HandlerTestsOut(
                    content="// Test handler test",
                    name="test_handler",
                    error_output=None
                )
            },
            refined_description=RefineOut(
                refined_description="Test application",
                error_output=None
            ),
            gherkin=GherkinOut(
                gherkin=None,
                reasoning=None,
                error_output=None
            ),
            trace_id="test-trace-id"
        )
        
        # Initialize interpolator and bake application
        interpolator = Interpolator(self.test_dir)
        interpolator.bake(app, self.output_dir)
        
        # Check if custom_tools.ts is generated using CUSTOM_TOOL_TEMPLATE
        custom_tools_path = os.path.join(self.output_dir, "app_schema", "src", "custom_tools.ts")
        self.assertTrue(os.path.exists(custom_tools_path), "custom_tools.ts not generated")
        
        with open(custom_tools_path, "r") as f:
            content = f.read()
        
        # Check if content contains signature elements from CUSTOM_TOOL_TEMPLATE
        self.assertIn("import type { CustomToolHandler }", content, 
                     "custom_tools.ts does not use CUSTOM_TOOL_TEMPLATE")
        self.assertIn("can_handle:", content, 
                     "custom_tools.ts does not include can_handle property")
        
        # Check if imports are generated correctly
        self.assertIn("import * as pica from", content,
                    "Module import not generated correctly")

if __name__ == "__main__":
    unittest.main()