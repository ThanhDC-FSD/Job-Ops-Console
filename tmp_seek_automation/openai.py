class _Message:
    def __init__(self, content=""):
        self.content = content

class _Choice:
    def __init__(self, message):
        self.message = message

class _Response:
    def __init__(self, content):
        self.choices = [_Choice(_Message(content))]

class _Completions:
    def create(self, *args, **kwargs):
        return _Response("")

class _Chat:
    completions = _Completions()

class OpenAI:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.chat = _Chat()
