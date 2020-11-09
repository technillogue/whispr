from typing import List, Tuple, Set
from collections import defaultdict
import json
import time
import os
import inspect
import pytest
from whispr import Whisperer, bidict


class MockLoop:
    def run(self) -> None:
        pass


class MockSignal:
    def __init__(self) -> None:
        self.outbox: List[Tuple[List[str], str, List[str]]] = []

    def sendMessage(self, msg: str, media: List[str], recip: List[str]) -> None:
        self.outbox.append((recip, msg, media))


class MockWhisperer(Whisperer):
    get_bus = staticmethod(lambda: {"org.asamk.Signal": MockSignal()})
    get_loop = staticmethod(MockLoop)

    def __init__(self, fname: str = "mock_users.json"):
        super().__init__()
        self.fname = fname
        self.followers = defaultdict(list)
        self.user_names = bidict()
        self.blocked: Set[str] = set()

    def take_outbox_for(self, number: str) -> List[str]:
        taken, kept = [], []
        for recipient, text, media in self.signal.outbox:
            if recipient == [number]:
                taken.append(text)
            else:
                kept.append((recipient, text, media))
        self.signal.outbox = kept
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

    def input(self, sender: str, text: str) -> None:
        self.receive(int(time.time()), sender, [], text, [])


@pytest.fixture(name="wisp")
def wisp_fixture() -> MockWhisperer:
    return MockWhisperer()

# i think i screwed this up, i wanted it to be cleared between tests
# and it isn't..

alice = "+" + "1" * 11  # mutuals with bob and carol
bob = "+" + "2" * 11
carol = "+" + "3" * 11
nancy = "+" + "4" * 11  # new
goofus = "+" + "5" * 11  # rude
xeres = "+" + "7" * 11  # follows zoe
yoric = "+" + "8" * 11  # follows xeres
zoe = "+" + "9" * 11  # follows yoric

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


def test_cache() -> None:
    wisp = MockWhisperer()
    json.dump(
        [{alice: "alice", bob: "bob"}, {alice: [bob]}, [nancy]],
        open("mock_users.json", "w"),
    )
    with wisp:
        wisp.run()
        wisp.input(bob, f"/follow {carol}")
        assert wisp.take_outbox_for(carol) == [
            "welcome to whispr. text STOP or BLOCK to not receive messages",
            "bob has followed you",
            "what would you like to be called?",
        ]
        wisp.input(carol, "carol")
        wisp.input(bob, "/unfollow alice")  # doesn't work
        wisp.input(carol, "block")
        wisp.input(nancy, "unblock")
    assert json.load(open("mock_users.json")) == [
        {alice: "alice", bob: "bob", carol: "carol", nancy: nancy},
        {alice: [], carol: [bob]},
        [carol],
    ]
    os.remove("mock_users.json")


def test_echo(wisp: MockWhisperer) -> None:
    assert wisp.do_echo({"line": "spam"}) == "spam"


def test_stop_start(wisp: MockWhisperer) -> None:
    wisp.input(alice, "hi")
    wisp.input(alice, "alice")
    wisp.input(alice, f"/invite {bob}")
    wisp.input(bob, "bob")
    wisp.input(alice, posts[3])
    wisp.take_outbox_for(bob)
    wisp.check_in_out(
        bob,
        "STOP",
        "i'll stop messaging you. text START or UNBLOCK to resume texts",
    )
    wisp.input(alice, posts[1])
    assert wisp.take_outbox_for(bob) == []
    wisp.check_in_out(bob, "START", "welcome back")
    wisp.check_in_out(bob, "START", "you weren't blocked")


def test_new_user(wisp: MockWhisperer) -> None:
    wisp.input(alice, "hi")
    assert wisp.take_outbox_for(alice) == [
        "welcome to whispr. text STOP or BLOCK to not receive messages",
        "hi yourself",
        "what would you like to be called?",
    ]
    wisp.input(alice, "alice")
    assert wisp.take_outbox_for(alice) == [
        "other users will now see you as alice"
    ]
    assert wisp.user_names[alice] == "alice"


def test_follow_new_user_flow(wisp: MockWhisperer) -> None:
    wisp.user_names[alice] = "alice"
    wisp.check_in_out(alice, "/following", "you aren't following anyone")
    wisp.check_in_out(alice, f"/follow {bob}", f"followed {bob}")
    assert wisp.take_outbox_for(bob) == [
        "welcome to whispr. text STOP or BLOCK to not receive messages",
        "alice has followed you",
        "what would you like to be called?",
    ]
    wisp.check_in_out(bob, "bob", "other users will now see you as bob")
    assert wisp.user_names[bob] == "bob"
    wisp.check_in_out(alice, "/following", "bob")
    wisp.check_in_out(bob, "/followers", "alice")
    wisp.input(bob, "hi alice")
    assert wisp.take_outbox_for(alice) == ["bob: hi alice"]


def test_invite_unfollow(wisp: MockWhisperer) -> None:
    wisp.user_names.update({alice: "alice", bob: "bob", nancy: "nancy"})
    wisp.check_in_out(alice, f"/invite {nancy}", f"invited {nancy}")
    assert wisp.take_outbox_for(nancy) == [
        "alice invited you to follow them on whispr. "
        "text (y)es or (n)o to accept"
    ]
    wisp.check_in_out(nancy, "yes", "followed alice")
    wisp.check_in_out(
        alice, f"/invite {nancy}", f"you're already following {nancy}"
    )

    wisp.check_in_out(nancy, "/unfollow alice", "unfollowed alice")
    wisp.check_in_out(nancy, "/unfollow alice", "you aren't following alice")

    wisp.check_in_out(bob, "/invite nancy", "invited nancy")
    wisp.check_in_out(alice, "/invite nancy", "invited nancy")
    assert wisp.take_outbox_for(nancy)
    wisp.input(nancy, "no")
    assert wisp.take_outbox_for(nancy) == [
        "didn't follow bob",
        "alice invited you to follow them on whispr. "
        "text (y)es or (n)o to accept",
    ]
    wisp.check_in_out(
        nancy,
        "asf;asdjf;llkas",
        "that didn't look like a response. "
        f"not following alice by default. if you do want to "
        f"follow them, text `/follow {alice}` or `/follow alice`",
    )


def test_multiple_followers(wisp: MockWhisperer) -> None:
    wisp.user_names.update({alice: "alice", bob: "bob", carol: "carol"})
    wisp.followers[alice] = [bob, carol]
    wisp.followers[bob] = [alice, carol]
    wisp.followers[carol] = [alice, bob]
    wisp.input(alice, posts[0])
    assert (
        wisp.take_outbox_for(bob)
        == wisp.take_outbox_for(carol)
        == ["alice: " + posts[0]]
    )
    assert wisp.take_outbox_for(alice) == []
    reply = "@alice what is this, 2006?"
    wisp.input(bob, reply)
    assert (
        wisp.take_outbox_for(alice)
        == wisp.take_outbox_for(carol)
        == ["bob: " + reply]
    )


def test_help(wisp: MockWhisperer) -> None:
    wisp.user_names[alice] = "alice"
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

def test_softblock(wisp: MockWhisperer) -> None:
    wisp.user_names.update({alice: "alice", bob: "bob"})
    wisp.followers[alice] = [bob]
    wisp.followers[bob] = [alice]
    # https://twitter.com/chordbug/status/1324853505245544454
    post1 = (
        "reply to this whisper with the name of a typeface that doesn't exist"
    )
    post2 = "@alice comic sans"
    # https://twitter.com/chordbug/status/1324767429474557952
    post3 = "every dang friday on here, I want to buy an accordion"
    wisp.input(alice, post1)
    assert wisp.take_outbox_for(bob) == ["alice: " + post1]
    wisp.input(bob, post2)
    assert wisp.take_outbox_for(alice) == ["bob: " + post2]
    wisp.check_in_out(alice, "/softblock bob", "softblocked bob")
    wisp.input(alice, post3)
    assert wisp.take_outbox_for(bob) == []
    wisp.check_in_out(alice, "/softblock nancy", "nancy isn't following you")
    wisp.check_in_out(
        alice, f"/softblock {nancy}", f"{nancy} isn't following you"
    )
    wisp.check_in_out(alice, "/softblock bob", "bob isn't following you")


def test_silly_error() -> None:
    wisp = MockWhisperer()
    wisp.user_names[alice] = "alice"
    wisp.log = None  # type: ignore
    expected_error = "'NoneType' object has no attribute 'append'"
    with pytest.raises(AttributeError, match=expected_error):
        wisp.input(alice, "hi")
    assert wisp.take_outbox_for(alice) == [
        "OOPSIE WOOPSIE!! Uwu We made a fucky wucky!!"
        "A wittle fucko boingo! The code monkeys at our headquarters "
        "are working VEWY HAWD to fix this!"
    ]
