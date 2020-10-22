from itertools import permutations
import json
from pydbus import SessionBus
from gi.repository import GLib


user_numbers = json.load(open("users.json"))

user_names = {number: name for name, number in user_numbers.items()}

followers = {u1: u2 for u1, u2 in permutations(user_numbers.values())}

def do_follow(): pass

def do_invite(): pass

def do_response(): pass

def do_unfollow(): pass

def do_block(): pass

def do_list(): pass


commands = {"follow": do_follow}

def msgRcv (timestamp, source, groupID, message, attachments):
    messages.append((timestamp, source, groupID, message, attachments))
    print ("Message", message, "from ", source)
#    if message.startswith("/"):
 #       commands[message[1:].split()[0]](source, message)
    name = usernames[source]
    for follower in followers[source]:
       signal.sendMessage(f"{name}: {message}", attachments, [follower]) 

    return


bus = SessionBus()
loop = GLib.MainLoop()

signal = bus.get('org.asamk.Signal')

signal.onMessageReceived = msgRcv
loop.run()
