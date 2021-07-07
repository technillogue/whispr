from typing import List, Set, Any, Optional as Opt, cast
from collections import defaultdict, UserString
import json
import time
import os
import inspect
import logging
import pytest
import whispr
from whispr import Message, bidict, SERVER_NUMBER


class OutgoingMessage(UserString):  # pylint: disable=too-many-ancestors
    def __init__(  # pylint: disable=super-init-not-called
        self, signal_command: dict
    ) -> None:
        # this is outdated by the forest fork of signal-cli
        self.attachments = signal_command.get("details", {}).get("attachments")
        self.recipient = signal_command["recipient"]
        self.data = signal_command["content"]


class FakePipe:
    def __init__(self, mock_signal: "MockSignalProc") -> None:
        self.mock_signal = mock_signal

    def write(self, b: bytes) -> None:
        signal_command = json.loads(b.decode("utf-8").strip())
        self.mock_signal.outbox.append(OutgoingMessage(signal_command))

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        if self.mock_signal.inbox:
            return self.mock_signal.inbox.pop(0).encode("utf-8")
        raise Exception("nothing to read")


class MockSignalProc:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        self.outbox: List[OutgoingMessage] = []
        self.inbox: List[str] = []
        self.stdout = FakePipe(self)
        self.stdin = FakePipe(self)

    def kill(self) -> None:
        pass


def make_envelope(
    source: str, msg: Opt[str], attach: Opt[List[str]] = None, **react: Any
) -> dict:
    reaction: Opt[dict] = react if react else None
    attachments = attach if attach else []
    return {
        "source": source,
        "dataMessage": {
            "timestamp": round(time.time() * 1000),
            "message": msg,
            "reaction": reaction,
            "attachments": [{"id": attachment} for attachment in attachments],
        },
    }


class MockWhisperer(whispr.Whisperer):
    def __init__(self, fname: str = "mock_users.json", empty: bool = False):
        whispr.Whisperer.Popen = MockSignalProc  # type: ignore
        super().__init__(fname)
        self.__enter__()
        if empty:  # should load mock_users.json
            self.user_names = cast(bidict, {})  # fuck pylint/mypy
            self.user_names = bidict()
            self.followers = defaultdict(list)
        self.blocked: Set[str] = set()

    def run_with_input(self, events: List[str]) -> None:
        assert isinstance(self.signal_proc, MockSignalProc)
        self.signal_proc.inbox = events
        self.run()

    def take_outbox_for(self, number: str) -> List[OutgoingMessage]:
        assert isinstance(self.signal_proc, MockSignalProc)
        taken, kept = [], []
        for msg in self.signal_proc.outbox:
            if msg.recipient == number:
                taken.append(msg)
            else:
                kept.append(msg)
        self.signal_proc.outbox = kept
        return taken

    def check_in_out(
        self, number: str, message: str, correct_response: str
    ) -> None:
        """
        pass one message to number and check it results in exactly one specific
        response to that number.
        """
        # this is assertion sugar, don't show it in tb
        __tracebackhide__ = True  # pylint: disable=unused-variable
        self.input(number, message)
        response = self.take_outbox_for(number)
        assert len(response) == 1
        assert response[0] == correct_response

    def input(
        self, sender: str, message: str, attachments: Opt[List[str]] = None
    ) -> int:
        msg = Message(self, make_envelope(sender, message, attachments))
        self.receive(msg)
        return msg.ts

    def input_reaction(self, sender: str, **kwargs: Any) -> int:
        kwargs["targetAuthor"] = SERVER_NUMBER
        kwargs["targetTimestamp"] = kwargs["ts"] * 1000
        msg = Message(self, make_envelope(sender, None, **kwargs))
        self.receive_reaction(msg)
        return msg.ts


@pytest.fixture(name="wisp")
def wisp_fixture() -> MockWhisperer:
    """for non-mutating use"""
    return MockWhisperer()


# dramatis personae
alice = "+" + "1" * 11  # mutuals with bob and carol
bob = "+" + "2" * 11
carol = "+" + "3" * 11
nancy = "+" + "4" * 11  # new
leatrice = "+" + "5" * 11  # loner
goofus = "+" + "6" * 11  # rude
xeres = "+" + "7" * 11  # follows zoe
yoric = "+" + "8" * 11  # follows xeres
zoe = "+" + "9" * 11  # follows yoric

# these aren't valid numbers
whispr.pn.is_valid_number = lambda number: True

posts = [
    "just setting up my whispr",  # https://twitter.com/jack/status/20
    "no",  # https://twitter.com/dril/status/922321981
    "Everything happens so much",
    # https://twitter.com/Horse_ebooks/status/218439593240956928
    "How Can Mirrors Be Real If Our Eyes Aren't Real",
    # https://twitter.com/jaden/status/329768040235413504
    """TSA agent (checking my ID): "Hawk, like that skateboarder Tony Hawk!"
Me: exactly
Her: "Cool, I wnder what he's up to these days"
Me: this""",  # https://twitter.com/tonyhawk/status/844308362070151168
]


def test_run(caplog: Any) -> None:
    caplog.set_level(logging.WARNING)
    wisp = MockWhisperer("testing_users.json", empty=True)
    inputs = [
        (bob, f"/follow {carol}"),
        (carol, "carol"),
        (carol, "wtf is this"),
        (bob, "/unfollow alice"),
        (carol, "block"),
        (nancy, "unblock"),
    ]
    inbox = [
        json.dumps({"envelope": make_envelope(source, message)})
        for source, message in inputs
    ] + [
        "spam",
        "{",
        json.dumps({"envelope": {}}),
    ]
    reactvelope = make_envelope(
        bob,
        None,
        targetAuthor=SERVER_NUMBER,
        targetTimestamp=round(time.time() * 1000),
        emoji="h",
    )
    inbox.insert(3, json.dumps({"envelope": reactvelope}))
    json.dump(
        [{alice: "alice", bob: "bob"}, {alice: [bob]}, [nancy]],
        open("testing_users.json", "w"),
    )
    with wisp:
        assert wisp.followers[alice] == [bob]
        with pytest.raises(Exception, match="nothing to read"):
            wisp.run_with_input(inbox)
        assert wisp.take_outbox_for(carol) == [
            "welcome to whispr, a social media that runs on signal. "
            "text STOP or BLOCK to not receive messages. type /help "
            "to view available commands.",
            "bob has followed you",
            "what would you like to be called?",
            "other users will now see you as carol",
            "reactions to 'wtf is this': bob: h",
            "i'll stop messaging you. text START or UNBLOCK to resume texts",
        ]
    assert [
        "signal-cli says: spam",
        "couldn't decode that",
        "that wasn't a real datamessage",
    ] == [rec.message for rec in caplog.records]
    assert json.load(open("testing_users.json")) == [
        {alice: "alice", bob: "bob", carol: "carol", nancy: nancy},
        {alice: [], carol: [bob]},
        [carol],
    ]
    os.remove("testing_users.json")


def test_echo(wisp: MockWhisperer) -> None:
    wisp.check_in_out(alice, "/echo spam", "spam")


def test_stop_start() -> None:
    wisp = MockWhisperer()
    wisp.check_in_out(
        bob,
        "STOP",
        "i'll stop messaging you. text START or UNBLOCK to resume texts",
    )
    wisp.input(alice, posts[1])
    assert wisp.take_outbox_for(bob) == []
    wisp.check_in_out(bob, "START", "welcome back")
    wisp.check_in_out(bob, "START", "you weren't blocked")


def test_new_user() -> None:
    wisp = MockWhisperer()
    wisp.input(nancy, "hi")
    assert wisp.take_outbox_for(nancy) == [
        "welcome to whispr, a social media that runs on signal. "
        "text STOP or BLOCK to not receive messages. type /help "
        "to view available commands.",
        "hi yourself",
        "what would you like to be called?",
    ]
    wisp.check_in_out(nancy, "nancy", "other users will now see you as nancy")
    wisp.check_in_out(
        nancy,
        "/name alice",
        "'alice' is already taken, use /name to set a different name",
    )
    assert wisp.user_names[nancy] == "nancy"


def test_follow() -> None:
    wisp = MockWhisperer()
    wisp.check_in_out(leatrice, "/following", "you aren't following anyone")
    wisp.check_in_out(leatrice, "/followers", "you don't have any followers")
    wisp.check_in_out(leatrice, f"/follow {bob}", f"followed {bob}")
    assert wisp.take_outbox_for(bob) == ["leatrice has followed you"]
    wisp.check_in_out(leatrice, "/following", "bob")
    wisp.check_in_out(bob, "/followers", "alice, leatrice")
    wisp.input(bob, "hi leatrice")
    assert wisp.take_outbox_for(leatrice) == ["bob: hi leatrice"]
    wisp.check_in_out(bob, "/follow leatrice", "followed leatrice")
    wisp.check_in_out(
        bob, "/follow leatrice", "you're already following leatrice"
    )
    wisp.check_in_out(
        bob,
        "/follow 11",
        "11 doesn't look a valid number or user. did you include the country code?",
    )


def test_invite_unfollow() -> None:
    wisp = MockWhisperer()
    wisp.check_in_out(alice, f"/invite {leatrice}", f"invited {leatrice}")
    assert wisp.take_outbox_for(leatrice) == [
        "alice invited you to follow them on whispr. "
        "text (y)es or (n)o to accept"
    ]
    wisp.check_in_out(leatrice, "yes", "followed alice")
    wisp.check_in_out(
        alice, f"/invite {leatrice}", f"you're already following {leatrice}"
    )

    wisp.check_in_out(leatrice, f"/unfollow {alice}", f"unfollowed {alice}")
    wisp.check_in_out(leatrice, "/unfollow alice", "you aren't following alice")

    wisp.check_in_out(bob, "/invite leatrice", "invited leatrice")
    wisp.check_in_out(alice, "/invite leatrice", "invited leatrice")
    assert wisp.take_outbox_for(leatrice)
    wisp.input(leatrice, "no")
    assert wisp.take_outbox_for(leatrice) == [
        "didn't follow bob",
        "alice invited you to follow them on whispr. "
        "text (y)es or (n)o to accept",
    ]
    wisp.check_in_out(
        leatrice,
        "asf;asdjf;llkas",
        "that didn't look like a response. "
        f"not following alice by default. if you do want to "
        f"follow them, text `/follow {alice}` or `/follow alice`",
    )


def test_default(wisp: MockWhisperer) -> None:
    wisp.input(alice, posts[0])
    assert (
        wisp.take_outbox_for(bob)
        == wisp.take_outbox_for(carol)
        == ["alice: " + posts[0]]
    )
    assert wisp.take_outbox_for(alice) == []
    reply = "@alice what is this, 2006?"
    wisp.input(bob, reply)
    assert wisp.take_outbox_for(alice) == ["bob: " + reply]
    attachments = ["wakeup.jpg", "loss.png"]
    wisp.input(xeres, posts[3], attachments)
    assert wisp.take_outbox_for(yoric)[0].attachments == [
        str(wisp.attachments_dir / attachment) for attachment in attachments
    ]


def test_help(wisp: MockWhisperer) -> None:
    wisp.input(alice, "/help")
    response = wisp.take_outbox_for(alice)[0]
    assert response.startswith("documented commands: ")
    commands = ("help", "echo", "name")
    for command in commands:
        assert command in response
        wisp.input(alice, f"/help {command}")
    assert wisp.take_outbox_for(alice) == [
        inspect.getdoc(getattr(wisp, f"do_{command}")) for command in commands
    ]
    wisp.check_in_out(alice, "/hlep", "no such command 'hlep'")
    wisp.check_in_out(alice, "/help hlep", "no such command 'hlep'")
    wisp.do_foo = lambda event: "fake"  # type: ignore
    wisp.check_in_out(alice, "/help foo", "foo isn't documented, sorry :(")


def test_softblock() -> None:
    wisp = MockWhisperer()
    wisp.followers[alice].append(goofus)
    wisp.followers[goofus].append(alice)
    # https://twitter.com/chordbug/status/1324853505245544454
    post1 = (
        "reply to this whisper with the name of a typeface that doesn't exist"
    )
    post2 = "@alice comic sans"
    # https://twitter.com/chordbug/status/1324767429474557952
    post3 = "every dang friday on here, I want to buy an accordion"
    wisp.input(alice, post1)
    assert wisp.take_outbox_for(goofus) == ["alice: " + post1]
    wisp.input(goofus, post2)
    assert wisp.take_outbox_for(alice) == ["goofus: " + post2]
    wisp.check_in_out(alice, "/softblock goofus", "softblocked goofus")
    wisp.input(alice, post3)
    assert wisp.take_outbox_for(goofus) == []
    wisp.check_in_out(
        alice, f"/softblock {nancy}", f"{nancy} isn't following you"
    )


def test_proxy() -> None:
    wisp = MockWhisperer()
    other_server = "+1" + "0" * 10
    wisp.check_in_out(
        alice, "/proxy", "you must be an admin to use this command"
    )
    wisp.admins.append(alice)
    wisp.check_in_out(alice, "/proxy", "entered proxy mode")
    wisp.check_in_out(alice, other_server + ":/echo spam", "sent")
    assert wisp.take_outbox_for(other_server) == ["/echo spam"]
    wisp.input(other_server, "spam")
    assert wisp.take_outbox_for(alice) == [other_server + ": spam"]
    wisp.check_in_out(alice, "/proxy", "exited proxy mode")
    # followup state notices alice left proxy mode and re-receives message
    wisp.input(other_server, "extra spam")
    assert wisp.take_outbox_for(other_server)[1] == "extra spam yourself"
    wisp.check_in_out(alice, "/echo hi", "hi")


def test_reaction() -> None:
    wisp = MockWhisperer()
    wisp.followers[alice].extend([xeres, yoric, zoe])
    ts = wisp.input(alice, posts[2])
    wisp.input_reaction(bob, emoji=":)", ts=ts)
    wisp.input_reaction(bob, emoji=":)", ts=-1)
    assert wisp.take_outbox_for(alice) == [f"reactions to '{posts[2]}': bob: :)"]
    wisp.input_reaction(carol, emoji=":(", ts=ts)
    assert wisp.take_outbox_for(alice) == [
        f"reactions to '{posts[2]}': bob: :), carol: :("
    ]
    wisp.input_reaction(xeres, emoji="h", ts=ts)
    wisp.take_outbox_for(alice)
    wisp.input_reaction(yoric, emoji="h", ts=ts)
    assert wisp.take_outbox_for(alice) == []


def test_silly_error() -> None:
    wisp = MockWhisperer()
    with pytest.raises(NotImplementedError):
        wb = whispr.WhispererBase()
        wb.do_default(Message(wisp, make_envelope(alice, "hi")))
    wisp.received_messages = None  # type: ignore
    expected_error = "'NoneType' object is not subscriptable"
    with pytest.raises(TypeError, match=expected_error):
        wisp.input(alice, "hi")
    assert wisp.take_outbox_for(alice) == [
        "OOPSIE WOOPSIE!! Uwu We made a fucky wucky!!"
        "A wittle fucko boingo! The code monkeys at our headquarters "
        "are working VEWY HAWD to fix this!"
    ]
