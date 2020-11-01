from typing import List, Tuple, Set, Any, Iterator
from collections import defaultdict
import json
import time
import os
import pytest
from whispr import Whisperer, bidict


class MockLoop:
    def call(self) -> None:
        pass


class MockSignal:
    def __init__(self) -> None:
        self.outbox: List[Tuple[List[str], str, List[str]]] = []

    def sendMessage(self, msg: str, media: List[str], recip: List[str]) -> None:
        self.outbox.append((recip, msg, media))


class MockWhisperer(Whisperer):
    get_bus = lambda self: {"org.asamk.Signal": MockSignal()}
    get_loop = MockLoop


    def __enter__(self) -> "MockWhisperer":
        self.followers = defaultdict(list)
        self.user_names = bidict()
        self.blocked: Set[str] = set()
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    clear = __enter__

    def outbox(self) -> List[Tuple[List[str], str, List[str]]]:
        return self.signal.outbox

    def take_outbox_for(self, number: str) -> List[str]:
        taken, kept = [], []
        for recipient, text, media in self.signal.outbox:
            if recipient == [number]:
                taken.append(text)
            else:
                kept.append((recipient, text, media))
        self.signal.outbox = kept
        return taken

    def input(self, sender: str, text: str) -> None:
        self.receive(int(time.time()), sender, [], text, [])


@pytest.fixture(name="wisp")  # type: ignore
def wisp_fixture() -> Iterator[MockWhisperer]:
    # should probably be named mock_whisperer, but that's annoyingly long
    # and "wisp" is kinda cute
    mock_whisperer = MockWhisperer("mock_users.json")
    json.dump([{}, {}, []], open("mock_users.json", "w"))
    with mock_whisperer:
        yield mock_whisperer
    os.remove("mock_users.json")
    print("teardown")


# ideally add a hypothesis test
def test_echo(wisp: MockWhisperer) -> None:
    assert wisp.do_echo({"line": "spam"}) == "spam"


alice = "+" + "1" * 11
bob = "+" + "2" * 11
carol = "+" + "3" * 11


def test_new_user(wisp: MockWhisperer) -> None:
    wisp.clear()
    wisp.input(alice, "/echo hi!")
    assert wisp.take_outbox_for(alice) == [
        "welcome to whispr. text STOP or BLOCK to not receive messages",
        "hi!",
        "what would you like to be called?",
    ]
    wisp.input(alice, "alice")
    assert wisp.take_outbox_for(alice) == [
        "other users will now see you as alice"
    ]
    assert wisp.user_names[alice] == "alice"


def test_follow_new_user(wisp: MockWhisperer) -> None:
    wisp.clear()
    wisp.user_names[alice] = "alice"
    wisp.input(alice, f"/follow {bob}")
    assert wisp.take_outbox_for(alice) == [f"followed {bob}"]
    assert wisp.take_outbox_for(bob) == [
        "welcome to whispr. text STOP or BLOCK to not receive messages",
        "alice has followed you",
        "what would you like to be called?",
    ]
    wisp.input(bob, "bob")
    assert wisp.take_outbox_for(bob) == ["other users will now see you as bob"]
    assert wisp.user_names[bob] == "bob"


# /follow
# followed X
# what would you like to be called?
# Foo
# you are now named Foo & users is correct
#

# follow someone who isn't tracked
# name from someone who isn't t

# follow -> name -> follow back
# invite -> name -> accept


# def test_cache():
# modify stuff and check it's the same


# def test_followup():
#   pass
