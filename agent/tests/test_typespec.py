import pytest
from policies.typespec import TypespecTaskNode, LLMFunction, PolicyException

class TestTypespecParser:
    def test_parse_complete_output(self):
        """Test parsing a well-formed output with reasoning, typespec, and functions."""
        test_output = """
        Here's my response:
        
        <reasoning>
        This is the reasoning section
        with multiple lines
        </reasoning>
        
        <typespec>
        model TestModel {
            name: string;
            value: integer;
        }
        
        interface TestInterface {
            @scenario(\"\"\"
            Scenario: Test scenario 1
            When user does something
            Then something happens
            \"\"\")
            @llm_func("Test function description")
            testFunction(options: TestModel): void;
            
            @scenario(\"\"\"
            Scenario: Test scenario 2
            When user does another thing
            Then another thing happens
            \"\"\")
            @llm_func("Another function description")
            anotherFunction(options: TestModel): void;
        }
        </typespec>
        """
        
        reasoning, definitions, functions = TypespecTaskNode.parse_output(test_output)
        
        assert reasoning == "This is the reasoning section\nwith multiple lines"
        assert "model TestModel" in definitions
        assert "interface TestInterface" in definitions
        assert len(functions) == 2
        
        assert functions[0].name == "testFunction"
        assert functions[0].description == "Test function description"
        assert "Scenario: Test scenario 1" in functions[0].scenario
        
        assert functions[1].name == "anotherFunction"
        assert functions[1].description == "Another function description"
        assert "Scenario: Test scenario 2" in functions[1].scenario


    def test_parse_missing_tags(self):
        """Test handling missing reasoning or typespec tags."""
        # Missing reasoning tag
        test_output_no_reasoning = """
        <typespec>
        model TestModel {
            name: string;
        }
        </typespec>
        """
        
        with pytest.raises(PolicyException) as excinfo:
            TypespecTaskNode.parse_output(test_output_no_reasoning)
        assert "Failed to parse output" in str(excinfo.value)
        
        # Missing typespec tag
        test_output_no_typespec = """
        <reasoning>
        Some reasoning
        </reasoning>
        """
        
        with pytest.raises(PolicyException) as excinfo:
            TypespecTaskNode.parse_output(test_output_no_typespec)
        assert "Failed to parse output" in str(excinfo.value)


    def test_parse_complex_scenarios(self):
        """Test parsing functions with multiple scenarios and complex formatting."""
        test_output = """
        <reasoning>Test reasoning</reasoning>
        
        <typespec>
        model TestModel {
            name: string;
        }
        
        interface ComplexInterface {
            @scenario(\"\"\"
            Scenario: First scenario
            Given a condition
            When something happens
            Then check result
            \"\"\")
            @scenario(\"\"\"
            Scenario: Second scenario
            Given another condition
            When another thing happens
            Then verify outcome
            \"\"\")
            @llm_func("Function with multiple scenarios")
            multiScenarioFunc(options: TestModel): void;
        }
        </typespec>
        """
        
        reasoning, definitions, functions = TypespecTaskNode.parse_output(test_output)
        
        assert reasoning == "Test reasoning"
        assert len(functions) == 1
        assert functions[0].name == "multiScenarioFunc"
        assert functions[0].description == "Function with multiple scenarios"
        assert "Scenario: Second scenario" in functions[0].scenario

        
    def test_parse_edge_case_formatting(self):
        """Test parsing with unusual whitespace and formatting."""
        test_output = """
        <reasoning>Edge case testing</reasoning>
        <typespec>
        model M { prop: string; }
        interface I {
            @scenario(\"\"\"
            Scenario: Minimal
            Test
            \"\"\")  @llm_func("Desc")   
            
            minFunc(options: M): void;
        }
        </typespec>
        """
        
        reasoning, definitions, functions = TypespecTaskNode.parse_output(test_output)
        
        assert reasoning == "Edge case testing"
        assert len(functions) == 1
        assert functions[0].name == "minFunc"
        assert functions[0].description == "Desc"
        assert "Scenario: Minimal" in functions[0].scenario


    def test_function_name_extraction(self):
        """Test extracting function names with various prefixes and suffixes."""
        test_output = """
        <reasoning>Function name testing</reasoning>
        <typespec>
        model M { prop: string; }
        interface I {
            @scenario(\"\"\"Scenario: Test\"\"\")
            @scenario(\"\"\"Scenario: Test\"\"\")
            @llm_func("Description")
            _underscoreFunc(options: M): void;
            
            @scenario(\"\"\"Scenario: Test\"\"\")
            @llm_func("Description")
            camelCaseFunc(options: M): void;
            
            @llm_func("Description")
            @scenario(\"\"\"Scenario: Test\"\"\")
            func123(options: M): void;
        }
        </typespec>
        """
        
        reasoning, definitions, functions = TypespecTaskNode.parse_output(test_output)
        
        assert len(functions) == 3
        assert functions[0].name == "_underscoreFunc"
        assert functions[1].name == "camelCaseFunc"
        assert functions[2].name == "func123" 