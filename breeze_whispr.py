#!/usr/bin/python3.9
import json
import logging
import time
from collections import defaultdict
from functools import wraps
from typing import Any, Awaitable, Callable, Optional

import asyncpg
import phonenumbers as pn
from bidict import bidict

from forest import pghelp, utils
from forest.core import Message, PayBot, Response, run_bot

Callback = Callable[[Message], Awaitable[Optional[str]]]


class Reaction:
    def __init__(self, reaction: dict) -> None:
        assert reaction
        self.emoji = reaction["emoji"]
        self.author = reaction["targetAuthor"]
        self.ts = round(reaction["targetTimestamp"] / 1000)


def takes_number(command: Callable) -> Callable:
    @wraps(command)  # keeps original name and docstring for /help
    async def wrapped_command(self: "Whisperer", msg: Message) -> str:
        if msg.arg1 in self.user_names.inverse:
            target_number = self.user_names.inverse[msg.arg1]  # type: ignore
            return await command(self, msg, target_number)
        try:
            # todo: parse (123) 456-6789 if it's multiple tokens
            assert msg.arg1
            parsed = pn.parse(msg.arg1, "US")
            assert pn.is_valid_number(parsed)
            target_number = pn.format_number(parsed, pn.PhoneNumberFormat.E164)
            return await command(self, msg, target_number)
        except (pn.phonenumberutil.NumberParseException, AssertionError):
            return (
                f"{msg.arg1} doesn't look a valid number or user. "
                "did you include the country code?"
            )

    return wrapped_command


def admin(command: Callable) -> Callable:
    @wraps(command)
    async def wrapped_command(self: "Whisperer", msg: Message) -> str:
        if msg.source == utils.get_secret("ADMIN"):
            return await command(self, msg)
        return "you must be an admin to use this command"

    wrapped_command.admin = True  # type: ignore
    return wrapped_command


class WhisprDB(pghelp.SimpleInterface):
    async def connect_pg(self) -> None:
        self.pool = await asyncpg.create_pool(self.database)
        pghelp.pools.append(self.pool)

    create = """CREATE TABLE IF NOT EXISTS persist (key TEXT, content JSON);"""


class Whisperer(PayBot):
    def __init__(self, bot_number: Optional[str] = None) -> None:
        self.paid: dict[str, bool] = {}
        self.db = pghelp.SimpleInterface(utils.get_secret("DATABASE_URL"))
        self.user_callbacks: dict[str, Callback] = {}
        # ...messages[timestamp][user] = msg
        self.received_messages: dict[int, dict[str, Message]] = defaultdict(dict)
        self.sent_messages: dict[int, dict[str, Message]] = defaultdict(dict)

        super().__init__(bot_number)

    async def start_process(self) -> None:
        async with self.db.get_connection() as conn:
            #            self.user_names: dict = cast(bidict, {})
            if utils.get_secret("MIGRATE"):
                await conn.execute(
                    "CREATE TABLE IF NOT EXISTS persist (key TEXT UNIQUE, content JSON);"
                )
            await conn.set_type_codec(
                "json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
            )
            maybe_names = await conn.fetchval(
                "SELECT content FROM persist WHERE key='user_names';"
            )
            self.user_names: bidict[str, str] = bidict(json.loads(maybe_names or "{}"))
            ret = await conn.fetchval(
                "SELECT content FROM persist WHERE key='followers'"
            )
            self.followers = defaultdict(list, ret or {})
            self.blocked: set[str] = set(
                await conn.fetchval("SELECT content FROM persist WHERE key='blocked';")
                or []
            )
        logging.info("starting")
        await super().start_process()

    async def async_shutdown(self, *_: Any, wait: bool = False) -> None:
        async with self.db.get_connection() as conn:
            vals = {
                "user_names": self.user_names,
                "followers": dict(self.followers),
                "blocked": list(self.blocked),
            }
            for key, content in vals.items():
                logging.info("inserting %s", key)
                await conn.execute(
                    "INSERT INTO persist VALUES ($1, $2) ON CONFLICT (key)  DO UPDATE SET key=$1, content=$2;",
                    key,
                    content,
                )
        await super().async_shutdown(wait=wait)

    async def sender_name(self, msg: Message) -> str:
        if msg.source:
            return self.user_names.get(msg.source, msg.name or "")
        return ""

    async def do_name(self, msg: Message) -> str:
        """/name [name]. set or change your name"""
        name = msg.arg1
        if not isinstance(name, str):
            return "missing name argument. usage: /name [name]"
        if name in self.user_names.inverse or name.endswith("proxied"):
            return f"'{name}' is already taken, use /name to set a different name"
        self.user_names[msg.source] = name
        return f"other users will now see you as {name}"

    async def register_callback(
        self, user: str, prompt: str, callback: Callback
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

            async def callback_bundle(msg: Message) -> Optional[str]:
                """
                dispatches the user's response to the previous callback, then
                sends the prompt for the next callback and registers that
                """
                resp = await previous_callback(msg)
                if resp:
                    await self.send_message(user, resp)
                self.user_callbacks[user] = callback
                return prompt

            self.user_callbacks[user] = callback_bundle
        else:
            await self.send_message(user, prompt)
            self.user_callbacks[user] = callback

    # maybe ideally really abstract out the specific messages and flow?

    async def send_message(
        self,
        recipient: str,
        message: str,
        attachments: Optional[list[str]] = None,
        force: bool = False,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """
        sends a message to recipient. if force is false, checks that the user
        hasn't blocked messages from whispr, and prompts new users for a name
        """
        if force or recipient not in self.blocked and message:  # replace
            if not force and recipient not in self.user_names:
                self.user_names[recipient] = recipient
                await super().send_message(
                    recipient,
                    "welcome to whispr, a social media that runs on signal. "
                    "text STOP or BLOCK to not receive messages. type /help "
                    "to view available commands.",
                )
                await super().send_message(recipient, message, attachments=attachments)
                await self.register_callback(
                    recipient, "what would you like to be called?", self.do_name
                )
            else:
                await super().send_message(recipient, message, attachments=attachments)

    fib = [0, 1]
    for i in range(20):
        fib.append(fib[-2] + fib[-1])

    async def receive_reaction(self, msg: Message) -> None:
        """
        route a reaction to the original message. if the number of reactions
        that message has is a fibonacci number, notify the message's author
        this is probably flakey, because signal only gives us timestamps and
        not message IDs
        """
        assert isinstance(msg.reaction, Reaction)
        react = msg.reaction
        logging.debug("reaction from %s targeting %s", msg.source, react.ts)
        self.received_messages[msg.ts][msg.source] = msg
        # stylistic choice to have less indents
        if react.author != self.bot_number or react.ts not in self.sent_messages:
            return

        target_msg = self.sent_messages[react.ts][msg.source]
        logging.debug("found target message %s", target_msg.text)
        target_msg.reactions[await self.sender_name(msg)] = react.emoji
        logging.debug("reactions: %s", repr(target_msg.reactions))
        count = len(target_msg.reactions)
        if count not in self.fib:
            return

        logging.debug("sending reaction notif")
        # maybe only show reactions that haven't been shown before?
        notif = ", ".join(
            f"{name}: {react}" for name, react in target_msg.reactions.items()
        )
        self.send_message(target_msg.source, f"reactions to '{target_msg.text}': {notif}")

    async def handle_message(self, message: Message) -> Response:
        if message.text and message.text.lower() in ("stop", "block"):
            self.blocked.add(message.source)
            return "i'll stop messaging you. " "text START or UNBLOCK to resume texts"
        if message.text and message.text.lower() in ("start", "unblock"):
            if message.source in self.blocked:
                self.blocked.remove(message.source)  # replace
                return "welcome back"
            return "you weren't blocked"
        if message.source in self.user_callbacks:
            return await self.user_callbacks.pop(message.source)(message)
        return await super().handle_message(message)

    async def default(self, message: Message) -> Response:
        """send a message to your followers"""
        if not message.text or message.group or "Documented commands" in message.text:
            return None
        if message.source not in self.user_names:
            # ensures they'll get a welcome message
            return f"{message.text} yourself"
        name = self.user_names[message.source]
        for follower in self.followers[message.source]:
            if message.attachments:
                attachments = [
                    attachment["filename"] for attachment in message.attachments
                ]
            else:
                attachments = []
            self.sent_messages[round(time.time())][follower] = message
            await self.send_message(follower, f"{name}: {message.text}", attachments)
        return None
        # ideally react to the message indicating it was sent?

    @takes_number
    async def do_follow(self, msg: Message, target_number: str) -> str:
        """/follow [number or name]. follow someone"""
        # if not self.paid.get(msg.source):
        #    return "this user is protected. send 0.5 mob to follow"

        # if self.user_info[target_number].protected:
        #     self.payments_manager = PaymentsManager()
        #     async def check_payment():
        #         payment_done = await self.payments_manager.get_payment(10)
        #         if payment_done:
        #             self.send(target_number, f"{await self.sender_name(msg)} has followed you")
        #             self.followers[target_number].append(msg.source)
        #         else:
        #             addr = await self.payments_manager.get_address_for(target_number)
        #             self.send(msg.source, f"pay 15 mob to {addr} for that")
        #     asyncio.create_task(check_payment())
        if msg.source not in self.followers[target_number]:
            await self.send(
                target_number, f"{await self.sender_name(msg)} has followed you"
            )
            self.followers[target_number].append(msg.source)
            self.paid[msg.source] = False
            # offer to follow back?
            return f"followed {msg.arg1}"
        return f"you're already following {msg.arg1}"

    @takes_number
    async def do_invite(self, msg: Message, target_number: str) -> str:
        """
        /invite [number or name]. invite someone to follow you
        """
        if target_number not in self.followers[msg.source]:
            await self.register_callback(
                target_number,
                f"{await self.sender_name(msg)} invited you to follow them on whispr. "
                "text (y)es or (n)o to accept",
                self.create_response_callback(msg.source),
            )
            return f"invited {msg.arg1}"
        return f"you're already following {msg.arg1}"

    def create_response_callback(self, inviter: str) -> Callback:
        inviter_name = self.user_names[inviter]

        async def response_callback(msg: Message) -> str:
            response = msg.text.lower()
            if response in "yes":  # matches substrings!
                self.followers[inviter].append(msg.source)
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

    async def do_followers(self, msg: Message) -> str:
        """/followers. list your followers"""
        source = msg.source
        if source in self.followers and self.followers[source]:
            return ", ".join(
                self.user_names[number] for number in self.followers[source]
            )
        return "you don't have any followers"

    async def do_following(self, msg: Message) -> str:
        """/following. list who you follow"""
        source = msg.source
        following = ", ".join(
            self.user_names[number]
            for number, followers in self.followers.items()
            if source in followers
        )
        if not following:
            return "you aren't following anyone"
        return following

    @takes_number
    async def do_softblock(self, msg: Message, target_number: str) -> str:
        """/softblock [number or name]. removes someone from your followers"""
        if target_number not in self.followers[msg.source]:
            return f"{msg.arg1} isn't following you"
        self.followers[msg.source].remove(target_number)
        return f"softblocked {msg.arg1}"

    @takes_number
    async def do_unfollow(self, msg: Message, target_number: str) -> str:
        """/unfollow [target_number or name]. unfollow someone"""
        if msg.source not in self.followers[target_number]:
            return f"you aren't following {msg.arg1}"
        self.followers[target_number].remove(msg.source)
        return f"unfollowed {msg.arg1}"

    @takes_number
    async def do_forceinvite(self, msg: Message, target_number: str) -> str:
        if target_number in self.followers[msg.source]:
            return f"{msg.arg1} is already following you"
        self.followers[msg.source].append(target_number)
        await self.send_message(
            target_number, f"you are now following {await self.sender_name(msg)}"
        )
        return f"{msg.arg1} is now following you"


if __name__ == "__main__":
    run_bot(Whisperer)
