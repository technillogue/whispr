import pytest
import whispr
import json

whisper.SessionBus = lambda: {"org.asmk.Signal": object()}

w = whispr.Whisperer("mock_users.json")

json.dump([{}, {}, []], "mock_users.json")


def test_context():
    # modify stuff and check it's the same
    pass 
def test_followup()A
    pass
