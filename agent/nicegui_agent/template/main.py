import os
from app.startup import startup
from nicegui import app, ui

app.on_startup(startup)
ui.run(storage_secret=os.environ.get('NICEGUI_STORAGE_SECRET', 'STORAGE_SECRET'))
