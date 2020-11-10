!/usr/bin/python3
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
from subprocess import Popen, PIPE
import json
import logging
from mypy_extensions import TypedDict
from bidict import bidict

SIGNAL_CLI = "./signal-cli-script -u +15345444555 daemon --json".split()

logging.basicConfig(
    level=logging.DEBUG, format="{levelname}: {message}", style="{"
)
# TODO: refactor into a class that matches signal-cli output
# https://code.activestate.com/recipes/52308-the-simple-but-handy-collector-of-a-bunch-of-named
Event = TypedDict(
    "Event",
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
    total=False,
)
State = DefaultDict[str, Deque[Callable[[Event], Optional[str]]]]


class WhispererBase:
    """
    handles receiving and sending messages
    blocking and unblocking
    append a function to state[number],
    it'll be called on the next message from that number
    handles new users
    """

    def __init__(self, fname: str = "users.json") -> None:
        self.fname = fname
        self.log: List[Event] = []
        self.state: State = defaultdict(deque)

    def __enter__(self) -> "WhispererBase":
        user_names, followers, blocked = json.load(open(self.fname))
        self.user_names = cast(bidict, {})  # tell pylint it's subscriptable
        self.user_names = bidict(user_names)
        self.followers = defaultdict(list, followers)
        self.blocked: Set[str] = set(blocked)
        self.signal_proc = Popen(
            SIGNAL_CLI, stdin=PIPE, stdout=PIPE, stderr=PIPE
        )
        logging.info("started signal-cli process")
        return self

    def __exit__(self, _: Any, value: Any, traceback: Any) -> None:
        json.dump(
            [dict(self.user_names), self.followers, list(self.blocked)],
            open(self.fname, "w"),
        )
        self.signal_proc.kill()
        logging.info("killed signal-cli process")

    def do_default(self, event: Union[Event, Event]) -> None:
        raise NotImplementedError

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
                return f"no such command '{argument}'"
        else:
            resp = "documented commands: " + ", ".join(
                name[2:] for name in dir(self) if name.startswith("do_")
            )
        return resp

    def do_name(self, event: Event) -> str:
        """/name [name]. set or change your name"""
        name = event["arg1"]
        if name in self.user_names.inverse:
            return f"{name} is already taken, use a different name"
        self.user_names[event["sender"]] = name
        return f"other users will now see you as {name}"

    def followup(self, number: str, message: str, hook: Callable) -> None:
        if not self.state[number]:
            self.send(number, message)
            self.state[number].append(hook)
        else:
            hooked = self.state[number].pop()

            def followup_wrapper(event: Event) -> Optional[str]:
                resp = hooked(event)
                if resp:
                    self.send(number, resp)
                self.state[number].append(hook)
                return message

            self.state[number].append(followup_wrapper)

    def send(self, recipient: str, message: str) -> None:
        if recipient not in self.blocked:
            if recipient not in self.user_names:
                self.user_names[recipient] = recipient
                self.send(
                    recipient,
                    "welcome to whispr. "
                    "text STOP or BLOCK to not receive messages",
                )
                self.send(recipient, message)
                self.followup(
                    recipient, "what would you like to be called?", self.do_name
                )
            else:
                self.signal_proc.stdin.write(
                    bytes(f"{recipient}:{message}\n", "utf-8")
                )
                self.signal_proc.stdin.flush()

    def receive_reaction(self, event: Event):
        pass

    def receive(self, event: Event) -> None:
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
                full_event = cast(Event, event)
                full_event["line"] = full_event["arg1"] = text
                full_event["tokens"] = text.split(" ")
                resp: Optional[str] = self.state[sender].popleft()(full_event)
            elif text.startswith("/"):
                command, *tokens = text[1:].split(" ")
                full_event = cast(Event, event)
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

    def run(self) -> None:
        # try also forwarding something from twitter
        # so you could test without needing two accounts
        # probably easiest yet expensive to just GET
        # setting up webhooks would be annoying
        while 1:
            line = self.signal_proc.stdout.readline().decode("utf-8")
            if not line.startswith("{"):
                logging.debug(f"signal-cli says: {line}")
                continue
            try:
                envelope = json.loads(line)["envelope"]
                event = envelope["dataMessage"]
                if not event:
                    raise KeyError
                event["sender"] = envelope["source"]
                event["ts"] = event["timestamp"]
                event["media"] = event["attachments"]
                event["groupID"] = event["groupInfo"]
                event = cast(Event, event)
                # so that i don't have to rewrite the code right away
                if event["reaction"]:
                    self.receive_reaction(event)
                else:
                    event["text"] = event["message"]
                    self.receive(event)
            except KeyError:
                logging.debug(f"not a datamessage: {line}")
            except json.JSONDecodeError:
                logging.log(f"couldn't decode {line}")


def do_echo(event: Event) -> str:
    """repeats what you say"""
    return event["line"]


class Whisperer(WhispererBase):
    def do_default(self, event: Union[Event, Event]) -> None:
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

    def do_follow(self, event: Event) -> str:
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

    def do_invite(self, event: Event) -> str:
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

        def invited(event: Event) -> str:
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

    def do_followers(self, event: Event) -> str:
        """/followers. list your followers"""
        sender = event["sender"]
        if sender in self.followers and self.followers[sender]:
            return ", ".join(
                self.user_names[number] for number in self.followers[sender]
            )
        return "you don't have any followers"

    def do_following(self, event: Event) -> str:
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
    def do_softblock(self, event: Event) -> str:
        """/softblock [number or name]. removes someone from your followers"""
        if event["arg1"] in self.user_names.inverse:
            number = self.user_names.inverse[event["arg1"]]
        else:
            number = event["arg1"]
        if number not in self.followers[event["sender"]]:
            return f"{event['arg1']} isn't following you"
        self.followers[event["sender"]].remove(number)
        return f"softblocked {event['arg1']}"

    def do_unfollow(self, event: Event) -> str:
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
