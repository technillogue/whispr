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
            command, argument = message[1:].split(maxsplit=1)
            try:
                resp = getattr(self, f"do_{command}")(
                    sender, argument, attachments
                )
            except AttributeError:
                resp = f"no such command {command}"
        else:
            resp = self.do_default(sender, message, attachments)
        if resp is not None:
            self.send(sender, resp)

    def do_default(self, sender, message, attachments) -> None:
        pass

    def do_help(self, sender, argument, attachments) -> str:
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
    def do_echo(self, sender, message, attachments) -> str:
        return message

    do_default = do_echo


with Whisperer() as whisperer:
    whisperer.run()
