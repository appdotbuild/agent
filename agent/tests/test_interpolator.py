import unittest
import tempfile
import shutil
from unittest.mock import Mock, patch
from agent.core.interpolator import Interpolator

class TestInterpolator(unittest.TestCase):
    def setUp(self):
        # Add temp directory as root_dir
        self.temp_dir = tempfile.mkdtemp()
        self.interpolator = Interpolator(root_dir=self.temp_dir)
    
    def tearDown(self):
        # Clean up temp directory
        shutil.rmtree(self.temp_dir)

    def test_basic_string_interpolation(self):
        template = "Hello {{name}}!"
        variables = {"name": "World"}
        result = self.interpolator._interpolate(template, variables)
        self.assertEqual(result, "Hello World!")

    def test_nested_object_interpolation(self):
        template = "{{user.name}} is {{user.age}} years old"
        variables = {
            "user": {
                "name": "John",
                "age": 30
            }
        }
        result = self.interpolator._interpolate(template, variables)
        self.assertEqual(result, "John is 30 years old")

    def test_array_interpolation(self):
        template = "Items: {% for item in items %}{{item}}, {% endfor %}"
        variables = {
            "items": ["apple", "banana", "orange"]
        }
        result = self.interpolator._interpolate(template, variables)
        self.assertEqual(result, "Items: apple, banana, orange, ")

    def test_conditional_interpolation(self):
        template = "{% if is_admin %}Admin{% else %}User{% endif %}: {{name}}"
        
        # Test admin case
        admin_vars = {
            "is_admin": True,
            "name": "John"
        }
        result = self.interpolator._interpolate(template, admin_vars)
        self.assertEqual(result, "Admin: John")
        
        # Test user case
        user_vars = {
            "is_admin": False,
            "name": "Jane"
        }
        result = self.interpolator._interpolate(template, user_vars)
        self.assertEqual(result, "User: Jane")

    def test_missing_variable(self):
        template = "Hello {{name}}!"
        variables = {}
        with self.assertRaises(KeyError):
            self.interpolator._interpolate(template, variables)

    def test_invalid_template_syntax(self):
        template = "Hello {{name!"  # Missing closing brace
        variables = {"name": "World"}
        with self.assertRaises(Exception):
            self.interpolator._interpolate(template, variables)

    def test_filter_application(self):
        template = "{{name|upper}}"
        variables = {"name": "john"}
        result = self.interpolator._interpolate(template, variables)
        self.assertEqual(result, "JOHN")

    def test_multiple_variables(self):
        template = "{{first_name}} {{last_name}} <{{email}}>"
        variables = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com"
        }
        result = self.interpolator._interpolate(template, variables)
        self.assertEqual(result, "John Doe <john@example.com>")

    def test_nested_control_structures(self):
        template = """
        {% for user in users %}
            {% if user.is_active %}
                {{user.name}} is active
            {% else %}
                {{user.name}} is inactive
            {% endif %}
        {% endfor %}
        """
        variables = {
            "users": [
                {"name": "John", "is_active": True},
                {"name": "Jane", "is_active": False},
                {"name": "Bob", "is_active": True}
            ]
        }
        result = self.interpolator._interpolate(template, variables)
        expected = """
                John is active
                Jane is inactive
                Bob is active
        """
        # Normalize whitespace for comparison
        self.assertEqual(
            ' '.join(result.split()),
            ' '.join(expected.split())
        )

    def test_custom_filters(self):
        def custom_greeting(name):
            return f"Hello, {name}!"

        self.interpolator.add_filter('greet', custom_greeting)
        
        template = "{{name|greet}}"
        variables = {"name": "John"}
        result = self.interpolator._interpolate(template, variables)
        self.assertEqual(result, "Hello, John!")

    def test_escape_html(self):
        template = "{{html_content|escape}}"
        variables = {
            "html_content": "<script>alert('test')</script>"
        }
        result = self.interpolator._interpolate(template, variables)
        self.assertEqual(
            result,
            "&lt;script&gt;alert(&#39;test&#39;)&lt;/script&gt;"
        )

    def test_whitespace_control(self):
        template = """
        {%- for item in items -%}
            {{item}}
        {%- endfor -%}
        """
        variables = {
            "items": ["a", "b", "c"]
        }
        result = self.interpolator._interpolate(template, variables)
        self.assertEqual(result, "abc")

    def test_template_inheritance(self):
        base_template = """
        {% block header %}Default Header{% endblock %}
        {% block content %}{% endblock %}
        {% block footer %}Default Footer{% endblock %}
        """
        
        child_template = """
        {% extends "base.html" %}
        {% block content %}Custom Content{% endblock %}
        """
        
        # Mock template loader
        with patch('jinja2.Environment.get_template') as mock_get_template:
            mock_base = Mock()
            mock_base.render.return_value = base_template
            mock_get_template.return_value = mock_base
            
            result = self.interpolator._interpolate(child_template, {})
            self.assertIn("Default Header", result)
            self.assertIn("Custom Content", result)
            self.assertIn("Default Footer", result)

    def test_error_handling(self):
        # Test undefined variable with strict undefined
        template = "{{undefined_var}}"
        with self.assertRaises(Exception):
            self.interpolator._interpolate(template, {}, strict=True)
        
        # Test with non-strict undefined
        result = self.interpolator._interpolate(template, {}, strict=False)
        self.assertEqual(result, "")

    def test_complex_data_structures(self):
        template = """
        {% for user in users %}
            {% if user.roles|length > 0 %}
                {{user.name}} has roles: 
                {% for role in user.roles %}
                    {{role.name}}{% if not loop.last %}, {% endif %}
                {% endfor %}
            {% endif %}
        {% endfor %}
        """
        variables = {
            "users": [
                {
                    "name": "John",
                    "roles": [
                        {"name": "admin"},
                        {"name": "user"}
                    ]
                },
                {
                    "name": "Jane",
                    "roles": [
                        {"name": "user"}
                    ]
                }
            ]
        }
        result = self.interpolator._interpolate(template, variables)
        expected = """
                John has roles: admin, user
                Jane has roles: user
        """
        # Normalize whitespace for comparison
        self.assertEqual(
            ' '.join(result.split()),
            ' '.join(expected.split())
        )

if __name__ == '__main__':
    unittest.main() 