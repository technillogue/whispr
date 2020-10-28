from typing import List, Tuple
from collections import defaultdict, deque
import json
import os
import pytest
from whispr import Whisperer, Event, FullEvent, State


class MockLoop:
    def call(self):
        pass


class MockSignal:
    def __init__(self):
        self.outbox = []

    def sendMessage(msg: str, media: List[str], recip: List[str]) -> None:
        self.outbox.append((msg, media, recip))


class MockWhisperer(Whisperer):
    def __init__(self, fname: str = "mock_users.json") -> None:
        self.fname = fname
        self.loop = MockLoop()
        self.signal = MockSignal()
        self.log: List[Event] = []
        self.state: State = defaultdict(deque)


@pytest.fixture
def wisp():
    # should probably be named mock_whisperer, but that's annoyingly long
    # and "wisp" is kinda cute
    mock_whisperer = MockWhisperer()
    json.dump([{}, {}, []], open("mock_users.json", "w"))
    with mock_whisperer:
        yield mock_whisperer
    os.remove("mock_users.json")
    print("teardown")


def test_echo(wisp):
    assert wisp.do_echo({"line": "spam"}) == "spam"

def test_follow():
    #     with w as whisperer:
    pass


# follow someone who isn't tracked
# name from someone who isn't t

# follow -> name -> follow back
# invite -> name -> accept


def test_cache():
    # modify stuff and check it's the same
    pass


def test_followup():
    pass


#
