from typing import Optional, Any
from itertools import permutations
import json
from pydbus import SessionBus
from gi.repository import GLib


class WhispererBase:
    def __init__(self) -> None:
        bus = SessionBus()
        self.loop = GLib.MainLoop()
        self.signal = bus.get("org.asamk.Signal")
        self.log = []
        self.state = {}
        # {number: callback?}

    def __enter__(self) -> "WhispererBase":
        data = json.load(open("users.json"))
        if isinstance(data, list):
            self.user_names, self.followers = data
        else:
            self.user_names = data
            self.followers = dict(permutations(self.user_names))
        return self

    def __exit__(self, _: Any, value: Any, traceback: Any) -> None:
        json.dump([self.user_names, self.followers], open("users.json", "w"))

    def send(self, recipient: str, message: str, attachments:Optional[list]=None) -> None:
        if attachments is None:
            attachments = []
        self.signal.sendMessage(message, attachments, [recipient])

    def receive(
        self, timestamp, sender: str, groupID, message: str, attachments: list
    ) -> None:
        self.log.append((timestamp, sender, groupID, message, attachments))
        print("Message", message, "from ", sender)
        if message.startswith("/"):
            command, *arguments = message[1:].split()
            try:
                resp = getattr(self, f"do_{command}")(
                    sender, arguments, attachments
                )
            except AttributeError:
                resp = f"no such command {command}"
        else:
            resp = self.do_default(sender, message, attachments)
        if resp is not None:
            self.send(sender, resp)

    def do_default(self, sender, arguments, attachments) -> None:
        pass

    def do_help(self, sender, arguments, attachments) -> str:
        argument = arguments[0]
        if argument:
            try:
                doc = getattr(self, f"do_{argument}").__doc__
                if doc:
                    return doc
                return f"{argument} isn't documented, sorry :("
            except AttributeError:
                return f"no such command {argument}"

    def run(self) -> None:
        self.signal.onMessageReceived = self.receive
        self.loop.run()


class Whisperer(WhispererBase):
    def do_echo(self, sender, arguments, attachments) -> str:
        """repeats what you say"""
        return " ".join(arguments)

    def do_name(self, sender, arguments, attachments) -> str:
        """/name [name]. set or change your name"""
        self.user_names[sender] = arguments[0]
        return f"other users will now see you as {arguments[0]}"

    def do_follow(self, sender, arguments, attachments) -> str:
        """/follow [number or name] [name]. follow someone, giving them a name"""
        try:
            identifier, name =  arguments
        except ValueError:
            number = arguments[0]
            name = number
        if identifier in self.user_names.values():
            name = identifier
            number = next(number for number, name in self.user_names.items() if name = identifier)
        else:
            number = identifier
        if not (number.startswith("+") and number[1:].isnumeric()):
            return f"{number} doesn't look a number. did you include the country code?"
        if number not in self.user_names:
            self.user_names[number] = name
            self.followers[number] = [sender]
            return f"followed {number}, named {name}"
        self.followers[number].append(sender)
        actual_name = self.user_names[number]
        return f"followed {number}. they have a name, it's {actual_name}"

    def do_followers(self, sender, arguments, attachments) -> str:
        """/followers. list your followers"""
        if sender in self.followers and self.followers[sender]:
            return ", ".join(self.followers[sender])
        return "you don't have any followers"

    def do_following(self, sender, arguments, attachments) -> str:
        """/following. list who you follow"""
        following = ", ".join(self.user_names[number] for number, followers in self.followers.items() if sender in followers)
        if not following:
            return "you aren't following anyone"
        return following

    def do_default(self, sender, arguments, attachments) -> None:
        """send a message to your followers"""
        name = self.user_names[sender]
        for follower in self.followers[sender]:
            self.send(follower, f"{name}: {' '.join(arguments)}", attachments)



with Whisperer() as whisperer:
    whisperer.run()
