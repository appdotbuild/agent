import pytest
from unittest.mock import patch, MagicMock
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
            
            testFunction(opts: TestModel): void;
            
            @llm_func("Another function description")
            @scenario(\"\"\"
            Scenario: Test scenario 2
            When user does another thing
            Then another thing happens
            \"\"\")
            anotherFunction(x: TestModel): void;

            @llm_func("3rd function description")
            @scenario(\"\"\"
            Scenario: Test scenario 3
            \"\"\")
            thirdFunction(_: TestModel): void;
        }
        </typespec>
        """
        
        reasoning, definitions, functions = TypespecTaskNode.parse_output(test_output)
        
        # Normalize whitespace for comparison
        normalized_reasoning = "\n".join(line.strip() for line in reasoning.splitlines())
        assert normalized_reasoning == "This is the reasoning section\nwith multiple lines"
        assert "model TestModel" in definitions
        assert "interface TestInterface" in definitions
        assert len(functions) == 3
        
        assert functions[0].name == "testFunction"
        assert functions[0].description == "Test function description"
        assert "Scenario: Test scenario 1" in functions[0].scenario
        
        assert functions[1].name == "anotherFunction"
        assert functions[1].description == "Another function description"
        assert "Scenario: Test scenario 2" in functions[1].scenario

        assert functions[2].name == "thirdFunction"
        assert functions[2].description == "3rd function description"
        assert "Scenario: Test scenario 3" in functions[2].scenario


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
            @llm_func("Function with multiple scenarios")
            @scenario(\"\"\"Scenario: First scenario
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
            multiScenarioFunc(xxx: TestModel): void;
        }
        </typespec>
        """
        
        reasoning, definitions, functions = TypespecTaskNode.parse_output(test_output)
        
        assert reasoning == "Test reasoning"
        assert len(functions) == 1
        assert functions[0].name == "multiScenarioFunc"
        assert functions[0].description == "Function with multiple scenarios"
        # Verify the scenario contains the content from the last specified scenario
        assert "Scenario: Second scenario" in functions[0].scenario
        assert "When another thing happens" in functions[0].scenario

        
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
            
            minFunc(param: M): void;
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
        
    def test_complex_typespec_with_nested_models(self):
        """Test parsing TypeSpec with nested models and complex type definitions."""
        test_output = """
        <reasoning>Testing complex models</reasoning>
        <typespec>
        model Address {
            street: string;
            city: string;
            zipCode: string;
            country: string;
        }
        
        model Person {
            id: integer;
            name: string;
            address: Address;
            tags: string[];
        }
        
        model CompanyDetails {
            employees: Person[];
            founded: utcDateTime;
            revenue: decimal;
        }
        
        interface ComplexAPI {
            @llm_func("Register a new person")
            @scenario(\"\"\"
            Scenario: Person Registration
            When user provides person information
            Then system should register the person
            \"\"\")
            registerPerson(person: Person): integer;
            
            @llm_func("Search for people by criteria")
            @scenario(\"\"\"
            Scenario: People Search
            When user provides search criteria
            Then system should return matching people
            \"\"\")
            searchPeople(criteria: {
                name?: string;
                country?: string;
                minAge?: integer;
            }): Person[];
        }
        </typespec>
        """
        
        reasoning, definitions, functions = TypespecTaskNode.parse_output(test_output)
        
        assert reasoning == "Testing complex models"
        assert len(functions) == 2
        assert functions[0].name == "registerPerson"
        assert functions[0].description == "Register a new person"
        assert "Scenario: Person Registration" in functions[0].scenario
        
        assert functions[1].name == "searchPeople"
        assert functions[1].description == "Search for people by criteria"
        assert "Scenario: People Search" in functions[1].scenario
        
        # Check that models were properly included
        assert "model Address" in definitions
        assert "model Person" in definitions
        assert "model CompanyDetails" in definitions
        
    def test_typescript_style_annotations(self):
        """Test parsing TypeSpec with TypeScript-style annotations and optional parameters."""
        test_output = """
        <reasoning>Testing TypeScript style</reasoning>
        <typespec>
        model Filter {
            query: string;
            limit?: integer;
            offset?: integer;
        }
        
        interface TypeScriptStyle {
            @llm_func("Query with TypeScript-style parameters")
            @scenario(\"\"\"
            Scenario: Typescript Style Query
            When user requests items with optional parameters
            Then system should return filtered items
            \"\"\")
            query(options: {
                query: string;
                filters?: Filter;
                sortBy?: "asc" | "desc";
            }): {
                items: string[];
                totalCount: integer;
            };
        }
        </typespec>
        """
        
        reasoning, definitions, functions = TypespecTaskNode.parse_output(test_output)
        
        assert reasoning == "Testing TypeScript style"
        assert len(functions) == 1
        assert functions[0].name == "query"
        assert functions[0].description == "Query with TypeScript-style parameters"
        assert "Scenario: Typescript Style Query" in functions[0].scenario
        
    def test_multiple_interfaces(self):
        """Test parsing TypeSpec with multiple interfaces."""
        test_output = """
        <reasoning>Testing multiple interfaces</reasoning>
        <typespec>
        model User {
            id: string;
            name: string;
        }
        
        model Product {
            id: string;
            name: string;
            price: decimal;
        }
        
        interface UserAPI {
            @llm_func("Create a new user")
            @scenario(\"\"\"
            Scenario: User Creation
            When admin provides user details
            Then system should create the user
            \"\"\")
            createUser(data: User): User;
        }
        
        interface ProductAPI {
            @llm_func("Create a new product")
            @scenario(\"\"\"
            Scenario: Product Creation
            When admin provides product details
            Then system should create the product
            \"\"\")
            createProduct(data: Product): Product;
        }
        </typespec>
        """
        
        reasoning, definitions, functions = TypespecTaskNode.parse_output(test_output)
        
        assert reasoning == "Testing multiple interfaces"
        assert len(functions) == 2
        assert functions[0].name == "createUser"
        assert functions[1].name == "createProduct"
        
        # Check that models and interfaces were properly included
        assert "model User" in definitions
        assert "model Product" in definitions
        assert "interface UserAPI" in definitions
        assert "interface ProductAPI" in definitions
        
    def test_special_types_and_arrays(self):
        """Test parsing TypeSpec with special types and array notations."""
        test_output = """
        <reasoning>Testing special types</reasoning>
        <typespec>
        model TimeRelated {
            date: plainDate;
            time: plainTime;
            dateTime: utcDateTime;
            offset: offsetDateTime;
            period: duration;
        }
        
        model ArrayTypes {
            strings: string[];
            nested: string[][];
            complexArray: {
                name: string;
                value: integer;
            }[];
        }
        
        interface DateTimeAPI {
            @llm_func("Schedule an appointment")
            @scenario(\"\"\"
            Scenario: Appointment Scheduling
            When user requests to schedule on a specific date and time
            Then system should create the appointment
            \"\"\")
            createAppointment ( req: {
                title: string;
                startTime: utcDateTime;
                endTime: utcDateTime;
                attendees: string[];
            }): void;
        }
        </typespec>
        """
        
        reasoning, definitions, functions = TypespecTaskNode.parse_output(test_output)
        
        assert reasoning == "Testing special types"
        assert len(functions) == 1
        assert functions[0].name == "createAppointment"
        assert "Scenario: Appointment Scheduling" in functions[0].scenario
        
        # Check for special types
        assert "plainDate" in definitions
        assert "plainTime" in definitions
        assert "utcDateTime" in definitions
        assert "offsetDateTime" in definitions
        assert "duration" in definitions
        
        # Check for array notations
        assert "string[]" in definitions
        assert "string[][]" in definitions
        
    def test_functions_with_return_types(self):
        """Test parsing functions with various return types."""
        test_output = """
        <reasoning>Testing return types</reasoning>
        <typespec>
        model Item {
            id: string;
            name: string;
        }
        
        model Result<T> {
            data: T;
            success: boolean;
            message?: string;
        }
        
        interface ReturnTypesAPI {
            @llm_func("Get void return")
            @scenario(\"\"\"
            Scenario: Void Return
            When user performs an action
            Then system should process without returning data
            \"\"\")
            voidReturn(id: string): void;
            
            @llm_func("Get primitive return")
            @scenario(\"\"\"
            Scenario: Primitive Return
            When user requests a count
            Then system should return the count
            \"\"\")
            getCount(
                filter:string): integer;
            
            @llm_func("Get complex return")
            @scenario(\"\"\"
            Scenario: Complex Return
            When user requests an item
            Then system should return the item with metadata
            \"\"\")
                getItem( id : string ): Result<Item>;
        }
        </typespec>
        """
        
        reasoning, definitions, functions = TypespecTaskNode.parse_output(test_output)
        
        assert reasoning == "Testing return types"
        assert len(functions) == 3
        assert functions[0].name == "voidReturn"
        assert functions[1].name == "getCount"
        assert functions[2].name == "getItem"
        
        # Check for return types
        assert "void" in definitions
        assert "integer" in definitions
        assert "Result<Item>" in definitions
    
    def test_complex_function_parameters(self):
        """Test parsing functions with complex parameter structures."""
        test_output = """
        <reasoning>Testing complex parameters</reasoning>
        <typespec>
        model BaseFilter {
            page: integer = 1;
            limit: integer = 10;
        }
        
        interface ComplexParamsAPI {
            @llm_func("Search with complex parameters")
            @scenario(\"\"\"
            Scenario: Complex Search
            When user provides nested search criteria
            Then system should return matching results
            \"\"\")
            search ( params: {
                query: string;
                filters: {
                    category?: string;
                    priceRange?: {
                        min?: decimal;
                        max?: decimal;
                    };
                    tags?: string[];
                } & BaseFilter;
                sort?: "asc" | "desc";
            }): {
                items: {
                    id: string;
                    name: string;
                    price: decimal;
                }[];
                total: integer;
            };
        }
        </typespec>
        """
        
        reasoning, definitions, functions = TypespecTaskNode.parse_output(test_output)
        
        assert reasoning == "Testing complex parameters"
        assert len(functions) == 1
        assert functions[0].name == "search"
        assert "Scenario: Complex Search" in functions[0].scenario
        
        # Check for complex parameter structures
        assert "BaseFilter" in definitions
        assert "& BaseFilter" in definitions  # Intersection type
        assert '"asc" | "desc"' in definitions  # Union type
        
    def test_void_return_type_validation(self):
        """Test that functions with void return types are flagged as errors."""
        
        test_output = """
        <reasoning>Testing void return validation</reasoning>
        <typespec>
        model TestModel {
            name: string;
        }
        
        interface VoidReturnAPI {
            @llm_func("Function with void return")
            @scenario(\"\"\"
            Scenario: Void Return Test
            When user calls a function
            Then system should validate return type
            \"\"\")
            voidFunction(options: TestModel): void;
            
            @llm_func("Function with non-void return")
            @scenario(\"\"\"
            Scenario: Non-void Return Test
            When user calls a function
            Then system should accept the return type
            \"\"\")
            validFunction(options: TestModel): boolean;
        }
        </typespec>
        """
        
        reasoning, definitions, functions = TypespecTaskNode.parse_output(test_output)
        
        assert reasoning == "Testing void return validation"
        assert len(functions) == 2
        assert functions[0].name == "voidFunction"
        assert functions[1].name == "validFunction"
        
        assert "void" in definitions
        assert "boolean" in definitions
        
    