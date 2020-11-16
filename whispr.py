#!/usr/bin/python3 -i
from typing import (
    Optional,
    Any,
    Union,
    List,
    Dict,
    Set,
    Callable,
    cast,
)
from collections import defaultdict
from textwrap import dedent
from subprocess import Popen, PIPE
import json
import time
import logging
from mypy_extensions import TypedDict
from bidict import bidict

NUMBER = open("number").read().strip()
SIGNAL_CLI = f"./signal-cli-script -u {NUMBER} daemon --json".split()

logging.basicConfig(
    level=logging.DEBUG, format="{levelname}: {message}", style="{"
)
# later: refactor into a class that matches signal-cli output
# https://code.activestate.com/recipes/52308-the-simple-but-handy-collector-of-a-bunch-of-named
Event = TypedDict(
    "Event",
    {
        "sender": str,
        "sender_name": str,
        "text": str,
        "ts": int,
        "reaction": dict,
        # added by receive
        "reactions": dict,
        "command": str,
        "line": str,
        "tokens": List[str],
        "arg1": str,
        "target": str,
    },
    total=False,
)
Callback = Callable[[Event], Optional[str]]


class WhispererBase:
    """
    handles communicating with signal-cli; sending messages; registering
    callbacks; routing received messages to callbacks, commands, or do_default;
    blocking and unblocking; new users; and the /name and /help commands
    """

    def __init__(self, fname: str = "users.json") -> None:
        self.fname = fname
        self.received_messages: Dict[int, Dict[str, Event]] = defaultdict(dict)
        self.sent_messages: Dict[int, Dict[str, Event]] = defaultdict(dict)
        self.user_callbacks: Dict[str, Callback] = {}

    # it's like this so it can be mocked out in tests
    Popen = Popen

    def __enter__(self) -> "WhispererBase":
        try:
            user_names, followers, blocked = json.load(open(self.fname))
        except FileNotFoundError:
            logging.info("didn't find saved user data")
            user_names, followers, blocked = [{}, {}, []]
        try:
            self.admins = json.load(open("admins"))
        except FileNotFoundError:
            self.admins = []
        self.user_names = cast(bidict, {})  # tell pylint it's subscriptable
        self.user_names = bidict(user_names)
        self.followers = defaultdict(list, followers)
        self.blocked: Set[str] = set(blocked)
        self.signal_proc = self.Popen(
            SIGNAL_CLI, stdin=PIPE, stdout=PIPE, stderr=PIPE
        )
        logging.info("started signal-cli process")
        return self

    def __exit__(self, _: Any, value: Any, traceback: Any) -> None:
        json.dump(
            [dict(self.user_names), self.followers, list(self.blocked)],
            open(self.fname, "w"),
        )
        logging.info("dumped user data to %s", self.fname)
        self.signal_proc.kill()
        logging.info("killed signal-cli process")

    def do_default(self, event: Event) -> None:
        raise NotImplementedError

    def do_help(self, event: Event) -> str:
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
                name[3:] for name in dir(self) if name.startswith("do_")
            )
        return resp

    def do_name(self, event: Event) -> str:
        """/name [name]. set or change your name"""
        name = event["arg1"]
        if name in self.user_names.inverse or name.endswith("proxied"):
            return (
                f"'{name}' is already taken, use /name to set a different name"
            )
        self.user_names[event["sender"]] = name
        return f"other users will now see you as {name}"

    def register_callback(
        self, user: str, prompt: str, callback: Callable
    ) -> None:
        """
        sends prompt to user. the user's response will be dispatched to
        the given callback instead of the usual flow.
        if there's already a callback registered for this user, the prompt
        will only be sent after that callback is resolved.
        """
        if user in self.user_callbacks:
            previous_callback = self.user_callbacks.pop(user)

            def callback_bundle(event: Event) -> Optional[str]:
                """
                dispatches the user's response to the previous callback, then
                sends the prompt for the next callback and registers that
                """
                resp = previous_callback(event)
                if resp:
                    self.send(user, resp)
                self.user_callbacks[user] = callback
                return prompt

            self.user_callbacks[user] = callback_bundle
        else:
            self.send(user, prompt)
            self.user_callbacks[user] = callback

    def send(self, recipient: str, message: str, force: bool = False) -> None:
        """
        sends a message to recipient. if force is false, checks that the user
        hasn't blocked messages from whispr, and prompts new users for a name
        """
        assert self.signal_proc.stdin
        if force or recipient not in self.blocked and message:
            if not force and recipient not in self.user_names:
                self.user_names[recipient] = recipient
                self.send(
                    recipient,
                    "welcome to whispr, a social media that runs on signal. "
                    "text STOP or BLOCK to not receive messages",
                )
                self.send(recipient, message)
                self.register_callback(
                    recipient, "what would you like to be called?", self.do_name
                )
            else:
                self.signal_proc.stdin.write(
                    bytes(f"{recipient}:{message}\n", "utf-8")
                )
                self.signal_proc.stdin.flush()

    fib = [0, 1]
    for i in range(20):
        fib.append(fib[-2] + fib[-1])

    def receive_reaction(self, event: Event) -> None:
        """
        route a reaction to the original message. if the number of reactions
        that message has is a fibonacci number, notify the message's author
        this is probably flakey, because signal only gives us timestamps and
        not message IDs
        """
        sender = event["sender"]
        sender_name = self.user_names[sender]
        reaction = event["reaction"]
        target_ts = round(reaction["targetTimestamp"] / 1000)
        logging.debug("reaction from %s targeting %s", sender, target_ts)
        self.received_messages[event["ts"]][sender] = event
        if reaction["targetAuthor"] == NUMBER:
            if target_ts in self.sent_messages:
                target_message = self.sent_messages[target_ts][sender]
                logging.debug("found target message %s", target_message["text"])
                target_message["reactions"][sender_name] = reaction["emoji"]
                logging.debug("reactions: %s", repr(target_message["reactions"]))
                count = len(target_message["reactions"])
                if count in self.fib:
                    logging.debug("sending reaction notif")
                    # maybe only show reactions that haven't been shown before?
                    reactions = ", ".join(
                        f"{name}: {react}"
                        for name, react in target_message["reactions"].items()
                    )
                    self.send(
                        target_message["sender"],
                        f"reactions to '{target_message ['text']}': {reactions}",
                    )

    def receive(self, event: Event) -> None:
        """
        dispatch a received message to a command handler or do_default,
        handling basic SMS-style compliance
        """
        sender: str = event["sender"]
        text: str = event["text"]
        try:
            event["reactions"] = {}
            self.received_messages[event["ts"]][sender] = event
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
            logging.info("%s: %s says %s", event["ts"], sender_name, text)
            if sender in self.user_callbacks:
                event["line"] = event["arg1"] = text
                event["tokens"] = text.split(" ")
                resp: Optional[str] = self.user_callbacks.pop(sender)(event)
            elif text.startswith("/"):
                command, *tokens = text[1:].split(" ")
                event["tokens"] = tokens
                event["arg1"] = tokens[0] if tokens else ""
                if event["arg1"] in self.user_names.inverse:
                    event["target"] = self.user_names.inverse[event["arg1"]]
                elif event["arg1"] in self.user_names:
                    event["target"] = event["arg1"]
                else:
                    event["target"] = ""
                event["line"] = " ".join(tokens)
                event["command"] = command
                if hasattr(self, f"do_{command}"):
                    resp = getattr(self, f"do_{command}")(event)
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
        """
        repeatedly reads json envelopes from signal-cli and massages the fields
        for receive_reaction and receive
        """
        assert self.signal_proc.stdout
        while 1:
            line = self.signal_proc.stdout.readline().decode("utf-8")
            if not line.startswith("{"):
                logging.warning("signal-cli says: %s", line.strip())
                continue
            try:
                envelope = json.loads(line)["envelope"]
                event = envelope["dataMessage"]
                if not event:
                    raise KeyError
                event["sender"] = envelope["source"]
                event["ts"] = round(event["timestamp"] / 1000)
                event = cast(Event, event)
                if event["reaction"]:
                    self.receive_reaction(event)
                else:
                    event["text"] = event["message"]
                    self.receive(event)
            except KeyError:
                logging.warning("not a datamessage: %s", line.strip())
            except json.JSONDecodeError:
                logging.error("can't decode %s", line.strip())


def do_echo(event: Event) -> str:
    """repeats what you say"""
    return event["line"]


class Whisperer(WhispererBase):
    """
    defines the rest of the commands
    """

    def do_default(self, event: Union[Event, Event]) -> None:
        """send a message to your followers"""
        sender = event["sender"]
        if sender not in self.user_names:
            self.send(sender, f"{event['text']} yourself")
            # ensures they'll get a welcome message
        else:
            name = self.user_names[sender]
            for follower in self.followers[sender]:
                self.sent_messages[round(time.time())][follower] = event
                self.send(follower, f"{name}: {event['text']}")
            # ideally react to the message indicating it was sent?

    do_echo = staticmethod(do_echo)

    def do_follow(self, event: Event) -> str:
        """/follow [number or name]. follow someone"""
        sender = event["sender"]
        number = event["target"] or event["arg1"]
        if not (number.startswith("+") and number[1:].isnumeric()):
            return (
                f"{event['arg1']} doesn't look a number. "
                "did you include the country code?"
            )
        if sender not in self.followers[number]:
            self.send(number, f"{event['sender_name']} has followed you")
            self.followers[number].append(sender)
            # offer to follow back?
            return f"followed {event['arg1']}"
        return f"you're already following {event['arg1']}"

    def do_invite(self, event: Event) -> str:
        """
        /invite [number or name]. invite someone to follow you
        """
        number = event["target"] or event["arg1"]
        if number not in self.followers[event["sender"]]:
            self.register_callback(
                number,
                f"{event['sender_name']} invited you to follow them on whispr. "
                "text (y)es or (n)o to accept",
                self.create_response_callback(event["sender"]),
            )
            return f"invited {event['arg1']}"
        return f"you're already following {event['arg1']}"

    def create_response_callback(self, inviter: str) -> Callback:
        inviter_name = self.user_names[inviter]

        def response_callback(event: Event) -> str:
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

        return response_callback

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
        number = event["target"] or event["arg1"]
        if number not in self.followers[event["sender"]]:
            return f"{event['arg1']} isn't following you"
        self.followers[event["sender"]].remove(number)
        return f"softblocked {event['arg1']}"

    def do_unfollow(self, event: Event) -> str:
        """/unfollow [number or name]. unfollow someone"""
        number = event["target"] or event["arg1"]
        if event["sender"] not in self.followers[number]:
            return f"you aren't following {event['arg1']}"
        self.followers[number].remove(event["sender"])
        return f"unfollowed {event['arg1']}"

    def do_proxy(self, event: Event) -> str:
        """
        toggle proxy mode. write number:message pairs and whispr will send them
        for you. you'll receive messages from those number(s) until you leave
        proxy mode
        """
        proxied_name = event["sender_name"]
        proxied = event["sender"]
        if proxied not in self.admins:
            return "you must be an admin to use this command"
        self.user_names[proxied] = proxied_name + "proxied"
        # should be caught by the callback
        assert not proxied_name.endswith("proxied")

        def response_callback(event: Event) -> None:
            """
            send responses to the proxied user, re-registering this callback
            until that user stops being proxied
            """
            if self.user_names[proxied].endswith("proxied"):
                self.send(proxied, event["sender_name"] + ": " + event["text"])
                self.register_callback(event["sender"], "", response_callback)
            else:
                self.send(event["sender"], "")
                self.receive(event)

        def proxy_callback(event: Event) -> Optional[str]:
            """
            parse responses as recipient:message to be forwarded
            recipients' responses will be sent back to the proxied user
            """
            if event["text"].startswith("/proxy"):
                self.user_names[proxied] = proxied_name
                return "exited proxy mode"
            target, msg = event["text"].split(":", 1)
            self.send(target, msg, force=True)
            if self.user_callbacks.get(target, None) is not response_callback:
                self.register_callback(target, "", response_callback)
            self.register_callback(proxied, "sent", proxy_callback)
            return None

        if self.user_callbacks.get(proxied, None) is not proxy_callback:
            self.register_callback(proxied, "", proxy_callback)
        return "entered proxy mode"


# dissappearing messages
# emoji?


if __name__ == "__main__":
    with Whisperer() as whisperer:
        whisperer.run()
