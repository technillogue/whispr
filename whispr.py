#!/usr/bin/python3 -i
from typing import (
    Optional,
    Any,
    Dict,
    Set,
    List,
    Callable,
    cast,
)
from collections import defaultdict
from textwrap import dedent
from subprocess import Popen, PIPE
from functools import wraps
import pathlib
import json
import time
import logging
from bidict import bidict
import phonenumbers as pn

SERVER_NUMBER = open("server_number").read().strip()
SIGNAL_CLI = f"./signal-cli-script -u {SERVER_NUMBER} daemon --json".split()

logging.basicConfig(
    level=logging.DEBUG, format="{levelname}: {message}", style="{"
)


class Reaction:
    def __init__(self, reaction: dict) -> None:
        assert reaction
        self.emoji = reaction["emoji"]
        self.author = reaction["targetAuthor"]
        self.ts = round(reaction["targetTimestamp"] / 1000)


class Message:
    """parses signal-cli output"""

    def __init__(self, wisp: "WhispererBase", envelope: dict) -> None:
        msg = envelope["dataMessage"]
        if not msg or (not msg["message"] and not msg["reaction"]):
            raise KeyError

        self.sender: str = envelope["source"]
        self.sender_name = wisp.user_names.get(self.sender, self.sender)
        self.ts = round(msg["timestamp"] / 1000)
        self.full_text = self.text = msg.get("message", "")
        try:
            self.reaction: Optional[Reaction] = Reaction(msg.get("reaction"))
        except (AssertionError, KeyError):
            self.reaction = None
        self.attachments = [
            str(wisp.attachments_dir / attachment["id"])
            for attachment in msg.get("attachments", [])
        ]

        self.reactions: Dict[str, str] = {}
        self.command: Optional[str] = None
        self.tokens: Optional[List[str]] = None
        if self.sender in wisp.user_callbacks:
            self.tokens = self.text.split(" ")
        elif self.text.startswith("/"):
            command, *self.tokens = self.text.split(" ")
            self.command = command[1:]  # remove /
            self.text = " ".join(self.tokens)

        self.arg1 = self.tokens[0] if self.tokens else None

    def __repr__(self) -> str:
        return f"<{self.sender_name}: {self.full_text}>"


Callback = Callable[[Message], Optional[str]]


class WhispererBase:
    """
    handles communicating with signal-cli; sending messages; registering
    callbacks; routing received messages to callbacks, commands, or do_default;
    blocking and unblocking; new users; and the /name and /help commands
    """

    def __init__(self, fname: str = "users.json") -> None:
        self.fname = fname
        self.user_callbacks: Dict[str, Callback] = {}
        # ...messages[timestamp][user] = msg
        self.received_messages: Dict[int, Dict[str, Message]] = defaultdict(dict)
        self.sent_messages: Dict[int, Dict[str, Message]] = defaultdict(dict)

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
        self.attachments_dir = (
            pathlib.Path.home() / ".local/share/signal-cli/attachments"
        )
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

    def do_default(self, msg: Message) -> None:
        raise NotImplementedError

    def do_help(self, msg: Message) -> str:
        """
        /help [command]. see the documentation for command, or all commands
        """
        if msg.arg1:
            try:
                doc = getattr(self, f"do_{msg.arg1}").__doc__
                if doc:
                    return dedent(doc).strip()
                return f"{msg.arg1} isn't documented, sorry :("
            except AttributeError:
                return f"no such command '{msg.arg1}'"
        else:
            resp = "documented commands: " + ", ".join(
                name[3:]
                for name in dir(self)
                if name.startswith("do_")
                and not hasattr(getattr(self, name), "admin")
            )
        return resp

    def do_name(self, msg: Message) -> str:
        """/name [name]. set or change your name"""
        name = msg.arg1
        if not isinstance(name, str):
            return "missing name argument. usage: /name [name]"
        if name in self.user_names.inverse or name.endswith("proxied"):
            return (
                f"'{name}' is already taken, use /name to set a different name"
            )
        self.user_names[msg.sender] = name
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
        assert user
        if user in self.user_callbacks:
            previous_callback = self.user_callbacks.pop(user)

            def callback_bundle(msg: Message) -> Optional[str]:
                """
                dispatches the user's response to the previous callback, then
                sends the prompt for the next callback and registers that
                """
                resp = previous_callback(msg)
                if resp:
                    self.send(user, resp)
                self.user_callbacks[user] = callback
                return prompt

            self.user_callbacks[user] = callback_bundle
        else:
            self.send(user, prompt)
            self.user_callbacks[user] = callback

    def send(
        self,
        recipient: str,
        message: str,
        attachments: Optional[List[str]] = None,
        force: bool = False,
    ) -> None:
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
                command: Dict[str, Any] = dict(
                    commandName="sendMessage",
                    recipient=recipient,
                    content=message,
                )
                if attachments:
                    command["details"] = {"attachments": attachments}
                self.signal_proc.stdin.write(
                    json.dumps(command).encode("utf-8") + b"\n"
                )
                self.signal_proc.stdin.flush()

    fib = [0, 1]
    for i in range(20):
        fib.append(fib[-2] + fib[-1])

    def receive_reaction(self, msg: Message) -> None:
        """
        route a reaction to the original message. if the number of reactions
        that message has is a fibonacci number, notify the message's author
        this is probably flakey, because signal only gives us timestamps and
        not message IDs
        """
        assert isinstance(msg.reaction, Reaction)
        react = msg.reaction
        logging.debug("reaction from %s targeting %s", msg.sender, react.ts)
        self.received_messages[msg.ts][msg.sender] = msg
        # stylistic choice to have less indents
        if react.author != SERVER_NUMBER or react.ts not in self.sent_messages:
            return

        target_msg = self.sent_messages[react.ts][msg.sender]
        logging.debug("found target message %s", target_msg.text)
        target_msg.reactions[msg.sender_name] = react.emoji
        logging.debug("reactions: %s", repr(target_msg.reactions))
        count = len(target_msg.reactions)
        if count not in self.fib:
            return

        logging.debug("sending reaction notif")
        # maybe only show reactions that haven't been shown before?
        notif = ", ".join(
            f"{name}: {react}" for name, react in target_msg.reactions.items()
        )
        self.send(
            target_msg.sender, f"reactions to '{target_msg.text}': {notif}"
        )

    def receive(self, msg: Message) -> None:
        """
        dispatch a received message to a command handler or do_default,
        handling basic SMS-style compliance
        """
        try:
            self.received_messages[msg.ts][msg.sender] = msg
            if msg.text.lower() in ("stop", "block"):
                self.send(
                    msg.sender,
                    "i'll stop messaging you. "
                    "text START or UNBLOCK to resume texts",
                )
                self.blocked.add(msg.sender)
                return
            if msg.text.lower() in ("start", "unblock"):
                if msg.sender in self.blocked:
                    self.blocked.remove(msg.sender)
                    self.send(msg.sender, "welcome back")
                    return
                self.send(msg.sender, "you weren't blocked")
                return
            logging.info(
                "%s: %s says %s", msg.ts, msg.sender_name, msg.full_text
            )
            if msg.sender in self.user_callbacks:
                resp: Optional[str] = self.user_callbacks.pop(msg.sender)(msg)
            elif msg.command:
                if hasattr(self, f"do_{msg.command}"):
                    resp = getattr(self, f"do_{msg.command}")(msg)
                else:
                    resp = f"no such command '{msg.command}'"
            else:
                resp = self.do_default(msg)  # type: ignore
            if resp is not None:
                self.send(msg.sender, resp)
        except:
            self.send(
                msg.sender,
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
                logging.info(line)
                msg = Message(self, json.loads(line)["envelope"])
                if msg.reaction:
                    self.receive_reaction(msg)
                else:
                    self.receive(msg)
            except KeyError:
                logging.debug("not a real datamessage: %s", line.strip())
            except json.JSONDecodeError:
                logging.error("can't decode %s", line.strip())


# def register_command(command: Callable) -> Callable:
#     command.is_command = True
#     command.name = command.__name__[3:]
#     return command
# class Command:
#     def __init__


def takes_number(command: Callable) -> Callable:
    @wraps(command)  # keeps original name and docstring for /help
    def wrapped_command(self: WhispererBase, msg: Message) -> str:
        if msg.arg1 in self.user_names.inverse:
            target_number = self.user_names.inverse[msg.arg1]
            return command(self, msg, target_number)
        try:
            parsed = pn.parse(msg.arg1, None)
            assert pn.is_valid_number(parsed)
            target_number = pn.format_number(parsed, pn.PhoneNumberFormat.E164)
            return command(self, msg, target_number)
        except (pn.phonenumberutil.NumberParseException, AssertionError):
            return (
                f"{msg.arg1} doesn't look a valid number or user. "
                "did you include the country code?"
            )

    return wrapped_command


def admin(command: Callable) -> Callable:
    @wraps(command)
    def wrapped_command(self: WhispererBase, msg: Message) -> str:
        if msg.sender in self.admins:
            return command(self, msg)
        return "you must be an admin to use this command"

    wrapped_command.admin = True  # type: ignore
    return wrapped_command


def do_echo(msg: Message) -> str:
    """repeats what you say"""
    return msg.text


class Whisperer(WhispererBase):
    """
    defines the rest of the commands
    """

    def do_default(self, msg: Message) -> None:
        """send a message to your followers"""
        if msg.sender not in self.user_names:
            self.send(msg.sender, f"{msg.text} yourself")
            # ensures they'll get a welcome message
        else:
            name = self.user_names[msg.sender]
            for follower in self.followers[msg.sender]:
                self.sent_messages[round(time.time())][follower] = msg
                self.send(follower, f"{name}: {msg.text}", msg.attachments)
            # ideally react to the message indicating it was sent?

    do_echo = staticmethod(do_echo)

    @takes_number
    def do_follow(self, msg: Message, target_number: str) -> str:
        """/follow [number or name]. follow someone"""
        if msg.sender not in self.followers[target_number]:
            self.send(target_number, f"{msg.sender_name} has followed you")
            self.followers[target_number].append(msg.sender)
            # offer to follow back?
            return f"followed {msg.arg1}"
        return f"you're already following {msg.arg1}"

    @takes_number
    def do_invite(self, msg: Message, target_number: str) -> str:
        """
        /invite [number or name]. invite someone to follow you
        """
        if target_number not in self.followers[msg.sender]:
            self.register_callback(
                target_number,
                f"{msg.sender_name} invited you to follow them on whispr. "
                "text (y)es or (n)o to accept",
                self.create_response_callback(msg.sender),
            )
            return f"invited {msg.arg1}"
        return f"you're already following {msg.arg1}"

    def create_response_callback(self, inviter: str) -> Callback:
        inviter_name = self.user_names[inviter]

        def response_callback(msg: Message) -> str:
            response = msg.text.lower()
            if response in "yes":  # matches substrings!
                self.followers[inviter].append(msg.sender)
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

    def do_followers(self, msg: Message) -> str:
        """/followers. list your followers"""
        sender = msg.sender
        if sender in self.followers and self.followers[sender]:
            return ", ".join(
                self.user_names[number] for number in self.followers[sender]
            )
        return "you don't have any followers"

    def do_following(self, msg: Message) -> str:
        """/following. list who you follow"""
        sender = msg.sender
        following = ", ".join(
            self.user_names[number]
            for number, followers in self.followers.items()
            if sender in followers
        )
        if not following:
            return "you aren't following anyone"
        return following

    @takes_number
    def do_softblock(self, msg: Message, target_number: str) -> str:
        """/softblock [number or name]. removes someone from your followers"""
        if target_number not in self.followers[msg.sender]:
            return f"{msg.arg1} isn't following you"
        self.followers[msg.sender].remove(target_number)
        return f"softblocked {msg.arg1}"

    @takes_number
    def do_unfollow(self, msg: Message, target_number: str) -> str:
        """/unfollow [target_number or name]. unfollow someone"""
        if msg.sender not in self.followers[target_number]:
            return f"you aren't following {msg.arg1}"
        self.followers[target_number].remove(msg.sender)
        return f"unfollowed {msg.arg1}"

    def do_proxy(self, msg: Message) -> str:
        """
        toggle proxy mode. write number:message pairs and whispr will send them
        for you. you'll receive messages from those number(s) until you leave
        proxy mode
        """
        proxied_name = msg.sender_name
        proxied = msg.sender
        if proxied not in self.admins:
            return "you must be an admin to use this command"
        self.user_names[proxied] = proxied_name + "proxied"
        # should be caught by the callback
        assert not proxied_name.endswith("proxied")

        def response_callback(msg: Message) -> None:
            """
            send responses to the proxied user, re-registering this callback
            until that user stops being proxied
            """
            if self.user_names[proxied].endswith("proxied"):
                text = msg.sender_name + ": " + msg.text
                self.send(proxied, text, msg.attachments)
                self.register_callback(msg.sender, "", response_callback)
            else:
                self.receive(msg)

        def proxy_callback(msg: Message) -> Optional[str]:
            """
            parse responses as recipient:message to be forwarded
            recipients' responses will be sent back to the proxied user
            """
            if msg.text.startswith("/proxy"):
                self.user_names[proxied] = proxied_name
                return "exited proxy mode"
            target, proxied_message = msg.text.split(":", 1)
            self.send(target, proxied_message, msg.attachments, force=True)
            if self.user_callbacks.get(target, None) is not response_callback:
                self.register_callback(target, "", response_callback)
            self.register_callback(proxied, "sent", proxy_callback)
            return None

        if self.user_callbacks.get(proxied, None) is not proxy_callback:
            self.register_callback(proxied, "", proxy_callback)
        return "entered proxy mode"

    @admin
    def do_debug(self, msg: Message) -> str:  # pylint: disable=no-self-use
        try:
            return eval(msg.text)  # pylint: disable=eval-used
        except Exception as e:  # pylint: disable=broad-except
            return str(e)


# dissappearing messages
# emoji?


if __name__ == "__main__":
    with Whisperer() as whisperer:
        whisperer.run()
