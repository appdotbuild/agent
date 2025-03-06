import uuid

class AppEntry:
    def __init__(self, application_description: str, id: str | None = None):
        self.id = id if id else uuid.uuid4().hex
        self.application_description = application_description


class AppAdjust:
    def __init__(self, application_description: str, id: str | None = None):
        self.id = id if id else uuid.uuid4().hex
        self.application_description = application_description


class AppSuccess:
    ...


