EXAMPLE_STARTUP_PY = """
from nicegui import Client, ui


def startup() -> None:
    @ui.page('/')
    def main_page() -> None:
        ui.markdown('Try running `pytest` on this project!')
        ui.button('Click me', on_click=lambda: ui.notify('Button clicked!'))
        ui.link('go to subpage', '/subpage')

    @ui.page('/subpage')
    def sub_page() -> None:
        ui.markdown('This is a subpage')
""".strip()


EXAMPLE_TEST_PY = """
from nicegui.testing import User


async def test_markdown_message(user: User) -> None:
    await user.open('/')
    await user.should_see('Try running') # Try running


async def test_button_click(user: User) -> None:
    await user.open('/')
    user.find('Click me').click()
    await user.should_see('Button clicked!')
""".strip()


EXAMPLE_TODO_APP = """
from dataclasses import dataclass, field
from typing import Callable, List
from nicegui import ui


@dataclass
class TodoItem:
    name: str
    done: bool = False


@dataclass
class ToDoList:
    title: str
    on_change: Callable
    items: List[TodoItem] = field(default_factory=list)

    def add(self, name: str, done: bool = False) -> None:
        self.items.append(TodoItem(name, done))
        self.on_change()

    def remove(self, item: TodoItem) -> None:
        self.items.remove(item)
        self.on_change()


@ui.refreshable
def todo_ui():
    if not todos.items:
        ui.label('List is empty.').classes('mx-auto')
        return
    ui.linear_progress(sum(item.done for item in todos.items) / len(todos.items), show_value=False)
    with ui.row().classes('justify-center w-full'):
        ui.label(f'Completed: {sum(item.done for item in todos.items)}')
        ui.label(f'Remaining: {sum(not item.done for item in todos.items)}')
    for item in todos.items:
        with ui.row().classes('items-center'):
            ui.checkbox(value=item.done, on_change=todo_ui.refresh).bind_value(item, 'done') \
                .mark(f'checkbox-{item.name.lower().replace(" ", "-")}')
            ui.input(value=item.name).classes('flex-grow').bind_value(item, 'name')
            ui.button(on_click=lambda item=item: todos.remove(item), icon='delete').props('flat fab-mini color=grey')


todos = ToDoList('My Weekend', on_change=todo_ui.refresh)
todos.add('Order pizza', done=True)
todos.add('New NiceGUI Release')
todos.add('Clean the house')
todos.add('Call mom')

with ui.card().classes('w-80 items-stretch'):
    ui.label().bind_text_from(todos, 'title').classes('text-semibold text-2xl')
    todo_ui()
    add_input = ui.input('New item').classes('mx-12').mark('new-item')
    add_input.on('keydown.enter', lambda: todos.add(add_input.value))
    add_input.on('keydown.enter', lambda: add_input.set_value(''))

if __name__ == '__main__':
    ui.run()
""".strip()


EXAMPLE_PANDAS_APP = """
import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

from nicegui import ui

df = pd.DataFrame(data={
    'col1': [x for x in range(4)],
    'col2': ['This', 'column', 'contains', 'strings.'],
    'col3': [x / 4 for x in range(4)],
    'col4': [True, False, True, False],
})


def update(*, df: pd.DataFrame, r: int, c: int, value):
    df.iat[r, c] = value
    ui.notify(f'Set ({r}, {c}) to {value}')


with ui.grid(rows=len(df.index)+1).classes('grid-flow-col'):
    for c, col in enumerate(df.columns):
        ui.label(col).classes('font-bold')
        for r, row in enumerate(df.loc[:, col]):
            if is_bool_dtype(df[col].dtype):
                cls = ui.checkbox
            elif is_numeric_dtype(df[col].dtype):
                cls = ui.number
            else:
                cls = ui.input
            cls(value=row, on_change=lambda event, r=r, c=c: update(df=df, r=r, c=c, value=event.value))
""".strip()


SYSTEM_PROMPT = f"""
You are software engineer.

Generate a NiceGUI application. Main application should be constructed in startup() function.
Applications should be covered with reasonable tests.

app/startup.py
```
{EXAMPLE_STARTUP_PY}
```

tests/test_button.py
```
{EXAMPLE_TEST_PY}
```

Rules for changing files:
- To apply local changes use SEARCH / REPLACE format.
- To change the file completely use the WHOLE format.
- When using SEARCH / REPLACE maintain precise indentation for both search and replace.
- Each block starts with a complete file path followed by newline with content enclosed with pair of ```.
- Each SEARCH / REPLACE block contains a single search and replace pair formatted with
<<<<<<< SEARCH
// code to find
=======
// code to replace it with
>>>>>>> REPLACE


Example WHOLE format:

app/index_page.py
```
@ui.page('/')
async def index():
    ui.input('general').bind_value(app.storage.general, 'text')
    ui.input('user').bind_value(app.storage.user, 'text')
    await ui.context.client.connected()
    ui.input('tab').bind_value(app.storage.tab, 'text')
```

Example SEARCH / REPLACE format:

app/metrics_tabs.py
```
<<<<<<< SEARCH
    with ui.tabs() as tabs:
        ui.tab('A')
        ui.tab('B')
        ui.tab('C')
=======
    with ui.tabs() as tabs:
        ui.tab('First')
        ui.tab('Second')
        ui.tab('Third')
>>>>>>> REPLACE
```
""".strip()


USER_PROMPT = """
{{ project_context }}

Implement user request:
{{ user_prompt }}
""".strip()
