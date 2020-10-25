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
from pydbus import SessionBus
from gi.repository import GLib


# hi! X has followed you. text stop or y/n
# you're following x
# what would you like to be called?
# -> call
# message queue?
# [invite msg, invite_response, name_msg, name_rsp]

Event = TypedDict(
    "Event",
    {
        "sender": str,
        "sender_name": str,
        "text": str,
        "media": List[str],
        "ts": str,
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

    def __init__(self) -> None:
        bus = SessionBus()
        self.loop = GLib.MainLoop()
        self.signal = bus.get("org.asamk.Signal")
        self.log: List[Event] = []
        self.state: State = defaultdict(deque)
        self.blocked: Set[str] = set()

    def __enter__(self) -> "WhispererBase":
        user_names, self.followers = json.load(open("users.json"))
        self.user_names = {} # tell pylint this is a dict
        self.user_names = bidict(user_names)
        return self

    def __exit__(self, _: Any, value: Any, traceback: Any) -> None:
        json.dump([self.user_names, self.followers], open("users.json", "w"))

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
                    "welcome to whispr."
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

    def receive(self, *args: Union[str, List[str]]) -> None:
        event = cast(
            Event, dict(zip(["sender", "ts", "groupID", "text", "media"], args))
        )
        self.log.append(event)
        sender: str = event["sender"]
        text: str = event["text"]
        if text.lower() in ("stop", "block"):
            self.send(
                sender,
                "i'll stop sending texts."
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
        if sender in self.state:
            event = cast(FullEvent, event)
            event["line"] = event["arg1"] = text
            event["tokens"] = text.split(" ")
            resp: Optional[str] = self.state[sender].popleft()(event)
        elif text.startswith("/"):
            command, *tokens = text[1:].split(" ")
            event = cast(FullEvent, event)
            event["tokens"] = tokens
            event["arg1"] = tokens[0]
            event["line"] = " ".join(tokens)
            event["command"] = command
            try:
                resp = getattr(self, f"do_{command}")(event)
            except AttributeError:
                resp = f"no such command {command}"
        else:
            resp = self.do_default(event)  # type: ignore
        if resp is not None:
            self.send(sender, resp)

    def do_default(self, event: FullEvent) -> None:
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
                    return dedent(doc)
                return f"{argument} isn't documented, sorry :("
            except AttributeError:
                return f"no such command {argument}"
        else:
            return "documented commands: " + ", ".join(
                name[3:]
                for name, value in self.__dict__
                if name.startswith("do_") and value.__doc__
            )

    def run(self) -> None:
        self.signal.onMessageReceived = self.receive
        self.loop.run()


def do_echo(event: FullEvent) -> str:
    """repeats what you say"""
    return event["line"]


class Whisperer(WhispererBase):
    do_echo = do_echo

    def do_follow(self, event: FullEvent) -> str:
        """/follow [number or name]. follow someone"""
        sender = event["sender"]
        if event["arg1"] in self.user_names.inverse:
            number = self.user_names.inverse[event["arg1"]]
        else:
            number = event["arg1"]
        if not (number.startswith("+") and number[1:].isnumeric()):
            return f"{number} doesn't look a number. did you include the country code?"
        if sender in self.followers[number]:
            return f"you're already following {number}"
        if number not in self.user_names:
            name = self.user_names[sender]
            self.send(
                number,
                (
                    "hi! this is whisprbot. "
                    f"{name} has followed you. "
                    "how would like to be called? "
                    "(text STOP or BLOCK to not receive messages again)"
                ),
            )
            self.state[number].append(self.do_name)
            self.followers[number] = [sender]
            return f"followed {number}"
        self.followers[number].append(sender)
        return f"followed {number}, they're called {self.user_names[number]}"

    def do_invite(self, event: FullEvent) -> str:
        """
        /invite [number or name]. invite someone to follow you
        """
        if event["arg1"] in self.user_names.inverse:
            number = self.user_names.inverse[event["arg1"]]
        else:
            number = event["arg1"]
        self.followup(
            number,
            f"{event['sender_name']} invited you to follow them on whispr. "
            "text (y)es or (n)o to accept",
            self.invite_respond(event["sender"]),
        )
        return f"invited {number}"

    def invite_respond(self, inviter: str) -> Callable:
        def invited(event: FullEvent) -> str:
            response = event["text"].lower()
            if response in "yes":  # matches substrings!
                self.followers[inviter].append(event["sender"])
                return f"followed {inviter}"
            if response in "no":
                return f"didn't follow {inviter}"
            return (
                "that didn't look like a response. "
                f"not following {inviter} by default. if you do want to "
                f"follow them, text /follow {inviter} or"
                f"/follow {self.user_names[inviter]}"
            )

        return invited

    def do_followers(self, event: FullEvent) -> str:
        """/followers. list your followers"""
        sender = event["sender"]
        if sender in self.followers and self.followers[sender]:
            return ", ".join(self.followers[sender])
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

    def do_default(self, event: Event) -> None:
        """send a message to your followers"""
        sender = event["sender"]
        name = self.user_names[sender]
        for follower in self.followers[sender]:
            self.send(follower, f"{name}: {event['text']}", event["media"])
        # maybe react to the message indicating it was sent


with Whisperer() as whisperer:
    whisperer.run()
