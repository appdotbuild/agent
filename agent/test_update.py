from anthropic import AnthropicBedrock
from application3 import Application3
from compiler.core import Compiler
import logging
import coloredlogs

# Setup logging
coloredlogs.install(level='INFO')
logger = logging.getLogger(__name__)

def test_update():
    # Initialize the components
    client = AnthropicBedrock(aws_profile='dev', aws_region='us-west-2')
    compiler = Compiler('botbuild/tsp_compiler', 'botbuild/app_schema')
    app = Application3(client, compiler)
    
    # Create a simple typespec
    typespec = '''<reasoning>
This is a simple to-do list app that allows users to create, update, delete, and list tasks.
</reasoning>
<typespec>
model Task {
  id: string;
  title: string;
  description?: string;
  completed: boolean;
  dueDate?: utcDateTime;
  createdAt: utcDateTime;
}

model CreateTaskOptions {
  title: string;
  description?: string;
  dueDate?: utcDateTime;
}

model UpdateTaskOptions {
  id: string;
  title?: string;
  description?: string;
  dueDate?: utcDateTime;
  completed?: boolean;
}

model DeleteTaskOptions {
  id: string;
}

model ListTasksOptions {
  completed?: boolean;
}

interface TodoApp {
  @scenario("""
  Scenario: Creating a new task
  When user says "Add a task to buy groceries"
  Then system creates a task with title "Buy groceries"
  """)
  @llm_func("Create a new task")
  createTask(options: CreateTaskOptions): Task;

  @scenario("""
  Scenario: Updating a task
  When user says "Mark task 123 as completed"
  Then system updates task 123 with completed = true
  """)
  @llm_func("Update an existing task")
  updateTask(options: UpdateTaskOptions): Task;

  @scenario("""
  Scenario: Deleting a task
  When user says "Delete task 123"
  Then system deletes task 123
  """)
  @llm_func("Delete a task")
  deleteTask(options: DeleteTaskOptions): void;

  @scenario("""
  Scenario: Listing tasks
  When user says "Show me all tasks"
  Then system returns all tasks
  """)
  @llm_func("List all tasks")
  listTasks(options: ListTasksOptions): Task[];
}
</typespec>'''
    
    try:
        # Call update_bot with the typespec
        bot = app.update_bot(typespec)
        print("Success! update_bot works correctly.")
        print(f"Typespec: {bot.typespec}")
        print(f"Drizzle: {bot.drizzle}")
        print(f"Typescript schema: {bot.typescript_schema}")
        print(f"Handler tests: {bot.handler_tests}")
        print(f"Handlers: {bot.handlers}")
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    test_update()