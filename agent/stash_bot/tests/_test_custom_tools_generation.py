import os
import tempfile
import shutil
import unittest
from core.interpolator import CUSTOM_TOOL_TEMPLATE

class CustomToolsGenerationTest(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.test_dir, "output")
        
    def tearDown(self):
        shutil.rmtree(self.test_dir)
    
    def test_custom_tools_interpolation_directly(self):
        """Test that custom_tools.ts is generated correctly with pica handlers by directly testing the interpolator"""
        import jinja2
        from capabilities import all_custom_tools
        
        # Filter custom tools to just include pica.calendar
        pica_tools = [t for t in all_custom_tools if t["name"] == "pica.calendar"]
        
        # Create Jinja2 environment and render template
        env = jinja2.Environment()
        template = env.from_string(CUSTOM_TOOL_TEMPLATE)
        rendered_content = template.render(handlers=pica_tools)
        
        # Check if content contains signature elements from CUSTOM_TOOL_TEMPLATE
        self.assertIn("import type { CustomToolHandler }", rendered_content, 
                     "custom_tools.ts does not use CUSTOM_TOOL_TEMPLATE")
        self.assertIn("can_handle:", rendered_content, 
                     "custom_tools.ts does not include can_handle property")
        
        # Check if imports are generated correctly for pica
        self.assertIn("import * as pica from", rendered_content,
                    "Pica module import not generated correctly")
        
        # Check if handler name is included correctly with dot replaced by underscore
        self.assertIn("name: 'pica_calendar'", rendered_content,
                    "Handler name not included correctly")

if __name__ == "__main__":
    unittest.main()