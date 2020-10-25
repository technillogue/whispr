from itertools import permutations
import json
from pydbus import SessionBus
from gi.repository import GLib

bus = SessionBus()
loop = GLib.MainLoop()

signal = bus.get("org.asamk.Signal")

# invite someone
# they get a y/n, their state listens for the answer before next input
# stop - blocklist await start
# send message to followers

# store followers
# store states
# dispatch to commands?


# json.dump([user_names, followers], open("users.json", "w"))


def do_follow(source, attachments, argument):
    pass


def do_invite():
    pass


def do_unfollow():
    pass


def do_block():
    pass


def do_list():
    pass


def do_echo(source, attachments, argument):
    signal.sendMessage(argument, attachments, [source])


def do_default(source, attachments, arguments):
    name = usernames[source]
    for follower in followers[source]:
        signal.sendMessage(f"{name}: {message}", attachments, [follower])


def msgRcv(timestamp, source, groupID, message, attachments):
    messages.append((timestamp, source, groupID, message, attachments))
    print("Message", message, "from ", source)
    if message.startswith("/"):
        command, argument = message[1:].split(maxsplit=1)
        if command in commands:
            commands[command](source, attachments, argument)
        else:
            signal.sendMessage("no such command", [], [source])
    else:
        do_default(source, attachments, message)


signal.onMessageReceived = msgRcv
loop.run()
