#!/usr/bin/python3
from typing import (
    Optional,
    Any,
    Union,
    List,
    Set,
    Callable,
    DefaultDict,
    Deque,
    cast,
)
from collections import defaultdict, deque
from textwrap import dedent
import json
from mypy_extensions import TypedDict
from bidict import bidict

try:
    from pydbus import SessionBus
    from gi.repository.GLib import MainLoop  # pylint: disable=import-error
except ModuleNotFoundError:
    # poetry can't package PyGObject's dependencies
    SessionBus = lambda: {}

    class MainLoop:  # type: ignore
        def run(self) -> None:
            pass


# maybe replace these with an actual class?
# https://code.activestate.com/recipes/52308-the-simple-but-handy-collector-of-a-bunch-of-named
# makes a compelling case for it being more pythonic
Event = TypedDict(
    "Event",
    {
        "sender": str,
        "sender_name": str,
        "text": str,
        "media": List[str],
        "ts": int,
        "groupID": str,
    },
)
FullEvent = TypedDict(
    "FullEvent",
    {
        "sender": str,
        "sender_name": str,
        "text": str,
        "media": List[str],
        "ts": str,
        "groupID": str,
        "command": str,
        "line": str,
        "tokens": List[str],
        "arg1": str,
    },
)
State = DefaultDict[str, Deque[Callable[[FullEvent], Optional[str]]]]


class WhispererBase:
    """
    handles receiving and sending messages
    blocking and unblocking
    append a function to state[number],
    it'll be called on the next message from that number
    handles new users
    """

    get_bus = staticmethod(SessionBus)
    get_loop = staticmethod(MainLoop)

    def __init__(self, fname: str = "users.json") -> None:
        bus = self.get_bus()
        self.fname = fname
        self.loop = self.get_loop()
        self.signal = bus.get("org.asamk.Signal")
        self.log: List[Event] = []
        self.state: State = defaultdict(deque)

    def __enter__(self) -> "WhispererBase":
        user_names, followers, blocked = json.load(open(self.fname))
        self.user_names = cast(bidict, {})  # tell pylint it's subscriptable
        self.user_names = bidict(user_names)
        self.followers = defaultdict(list, followers)
        self.blocked: Set[str] = set(blocked)
        return self

    def __exit__(self, _: Any, value: Any, traceback: Any) -> None:
        json.dump(
            [dict(self.user_names), self.followers, list(self.blocked)],
            open(self.fname, "w"),
        )

    def followup(self, number: str, message: str, hook: Callable) -> None:
        if not self.state[number]:
            self.send(number, message)
            self.state[number].append(hook)
        else:
            hooked = self.state[number].pop()

            def followup_wrapper(event: FullEvent) -> Optional[str]:
                resp = hooked(event)
                if resp:
                    self.send(number, resp)
                self.state[number].append(hook)
                return message

            self.state[number].append(followup_wrapper)

    def send(
        self, recipient: str, message: str, media: Optional[list] = None
    ) -> None:
        if media is None:
            media = []
        if recipient not in self.blocked:
            if recipient not in self.user_names:
                self.user_names[recipient] = recipient
                self.send(
                    recipient,
                    "welcome to whispr. "
                    "text STOP or BLOCK to not receive messages",
                )
                self.signal.sendMessage(message, media, [recipient])
                self.followup(
                    recipient, "what would you like to be called?", self.do_name
                )
            else:
                self.signal.sendMessage(message, media, [recipient])

    def do_name(self, event: FullEvent) -> str:
        """/name [name]. set or change your name"""
        name = event["arg1"]
        self.user_names[event["sender"]] = name
        return f"other users will now see you as {name}"

    def receive(self, *args: Union[int, str, List[str]]) -> None:
        event = cast(
            Event,
            dict(zip(["ts", "sender", "groupID", "text", "media"], args)),
        )
        sender: str = event["sender"]
        text: str = event["text"]
        try:
            self.log.append(event)
            if text.lower() in ("stop", "block"):
                self.send(
                    sender,
                    "i'll stop messaging you. "
                    "text START or UNBLOCK to resume texts",
                )
                self.blocked.add(sender)
                return
            if text.lower() in ("start", "unblock"):
                if sender in self.blocked:
                    self.blocked.remove(sender)
                    self.send(sender, "welcome back")
                else:
                    self.send(sender, "you weren't blocked")
                return
            if sender in self.user_names:
                sender_name = self.user_names[sender]
            else:
                sender_name = sender
            event["sender_name"] = sender_name
            print("Message", text, "from ", sender_name)
            if self.state[sender]:
                full_event = cast(FullEvent, event)
                full_event["line"] = full_event["arg1"] = text
                full_event["tokens"] = text.split(" ")
                resp: Optional[str] = self.state[sender].popleft()(full_event)
            elif text.startswith("/"):
                command, *tokens = text[1:].split(" ")
                full_event = cast(FullEvent, event)
                full_event["tokens"] = tokens
                full_event["arg1"] = tokens[0] if tokens else ""
                full_event["line"] = " ".join(tokens)
                full_event["command"] = command
                if hasattr(self, f"do_{command}"):
                    resp = getattr(self, f"do_{command}")(full_event)
                else:
                    resp = f"no such command '{command}'"
            else:
                resp = self.do_default(event)  # type: ignore
            if resp is not None:
                self.send(sender, resp)
        except:
            self.send(
                sender,
                "OOPSIE WOOPSIE!! Uwu We made a fucky wucky!!"
                "A wittle fucko boingo! The code monkeys at our headquarters "
                "are working VEWY HAWD to fix this!",
                # source: https://knowyourmeme.com/memes/oopsie-woopsie
            )
            raise

    def do_default(self, event: Union[Event, FullEvent]) -> None:
        raise NotImplementedError

    def do_help(self, event: FullEvent) -> str:
        """
        /help [command]. see the documentation for command, or all commands
        """
        if event["arg1"]:
            argument = event["arg1"]
            try:
                doc = getattr(self, f"do_{argument}").__doc__
                if doc:
                    return dedent(doc).strip()
                return f"{argument} isn't documented, sorry :("
            except AttributeError:
                return f"no such command {argument}"
        else:
            resp = "documented commands: " + ", ".join(
                name[3:]
                for name in dir(self)
                if name.startswith("do_")
                and getattr(self, name).__doc__
                and name != "do_default"
            )  # doesn't work?
            return resp

    def run(self) -> None:
        self.signal.onMessageReceived = self.receive
        self.loop.run()


def do_echo(event: FullEvent) -> str:
    """repeats what you say"""
    return event["line"]


class Whisperer(WhispererBase):
    def do_default(self, event: Union[FullEvent, Event]) -> None:
        """send a message to your followers"""
        sender = event["sender"]
        if sender not in self.user_names:
            self.send(sender, f"{event['text']} yourself")
            # ensures they'll get a welcome message
        else:
            name = self.user_names[sender]
            for follower in self.followers[sender]:
                self.send(follower, f"{name}: {event['text']}", event["media"])
            # ideally react to the message indicating it was sent

    do_echo = staticmethod(do_echo)

    def do_follow(self, event: FullEvent) -> str:
        """/follow [number or name]. follow someone"""
        sender = event["sender"]
        if event["arg1"] in self.user_names.inverse:
            number = self.user_names.inverse[event["arg1"]]
        else:
            number = event["arg1"]
        if not (number.startswith("+") and number[1:].isnumeric()):
            return f"{number} doesn't look a number. did you include the country code?"
        if sender not in self.followers[number]:
            self.send(number, f"{event['sender_name']} has followed you")
            self.followers[number].append(sender)
            # offer to follow back?
            return f"followed {event['arg1']}"
        return f"you're already following {number}"

    def do_invite(self, event: FullEvent) -> str:
        """
        /invite [number or name]. invite someone to follow you
        """
        if event["arg1"] in self.user_names.inverse:
            number = self.user_names.inverse[event["arg1"]]
        else:
            number = event["arg1"]
        if number not in self.followers[event["sender"]]:
            self.followup(
                number,
                f"{event['sender_name']} invited you to follow them on whispr. "
                "text (y)es or (n)o to accept",
                self.invite_respond(event["sender"]),
            )
            return f"invited {event['arg1']}"
        return f"you're already following {event['arg1']}"

    def invite_respond(self, inviter: str) -> Callable:
        inviter_name = self.user_names[inviter]

        def invited(event: FullEvent) -> str:
            response = event["text"].lower()
            if response in "yes":  # matches substrings!
                self.followers[inviter].append(event["sender"])
                return f"followed {inviter_name}"
            if response in "no":
                return f"didn't follow {inviter_name}"
            return (
                "that didn't look like a response. "
                f"not following {inviter_name} by default. if you do want to "
                f"follow them, text `/follow {inviter}` or "
                f"`/follow {inviter_name}`"
            )

        return invited

    def do_followers(self, event: FullEvent) -> str:
        """/followers. list your followers"""
        sender = event["sender"]
        if sender in self.followers and self.followers[sender]:
            return ", ".join(
                self.user_names[number] for number in self.followers[sender]
            )
        return "you don't have any followers"

    def do_following(self, event: FullEvent) -> str:
        """/following. list who you follow"""
        sender = event["sender"]
        following = ", ".join(
            self.user_names[number]
            for number, followers in self.followers.items()
            if sender in followers
        )
        if not following:
            return "you aren't following anyone"
        return following

    # maybe softblock/unfollow followers/following should reuse code somehow?
    def do_softblock(self, event: FullEvent) -> str:
        """/softblock [number or name]. removes someone from your followers"""
        if event["arg1"] in self.user_names.inverse:
            number = self.user_names.inverse[event["arg1"]]
        else:
            number = event["arg1"]
        if number not in self.followers[event["sender"]]:
            return f"{event['arg1']} isn't following you"
        self.followers[event["sender"]].remove(number)
        return f"softblocked {event['arg1']}"

    def do_unfollow(self, event: FullEvent) -> str:
        """/unfollow [number or name]. unfollow someone"""
        if event["arg1"] in self.user_names.inverse:
            number = self.user_names.inverse[event["arg1"]]
        else:
            number = event["arg1"]
        if event["sender"] not in self.followers[number]:
            return f"you aren't following {event['arg1']}"
        self.followers[number].remove(event["sender"])
        return f"unfollowed {event['arg1']}"


# dissappearing messages
# emoji?


if __name__ == "__main__":
    with Whisperer() as whisperer:
        whisperer.run()
