"""
File Library Bot
=================
A Telegram bot with three jobs:

1. Search a library of files by word or by first letter, and deliver the
   actual file (not just a link) to the user.
2. Only "authorized" users can use the bot at all (Layer 1) — random
   strangers who find the bot publicly on Telegram can't do anything with it.
3. Even an authorized user needs a separate, time-limited approval from an
   admin before they can actually receive any *specific* file (Layer 2) —
   this is the "protect file info, not everyone needs every file every time"
   layer. Access to a file expires automatically after DEFAULT_ACCESS_DAYS.

Any number of admins can approve/deny both kinds of requests — whichever
admin taps first "wins" (the pending request is removed immediately on the
first tap), so two admins can't double-process the same request.

Files themselves are never stored on this machine. An admin registers a
file by simply forwarding it to the bot once; Telegram keeps hosting the
actual bytes, and the bot only ever remembers the file's `file_id` plus
whatever name/keyword you give it. Delivery uses copy_message (not
forward), so recipients never see where the file originally came from.
"""

import json
import os
import logging
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN, ADMIN_IDS, DEFAULT_ACCESS_DAYS

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USERS_FILE = "users.json"
LIBRARY_FILE = "library.json"
ACCESS_FILE = "access.json"
WISHLIST_FILE = "wishlist.json"

# Conversation states
ADD_FILE_WAITING_NAME = 1
SEARCH_WAITING_QUERY = 2

DATE_FMT = "%Y-%m-%d %H:%M"


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------
# Every save goes through _atomic_write_json: write to a temp file, then
# os.replace() it into place. os.replace is atomic on both Windows and
# Linux, so a crash or power loss mid-save can never leave a half-written,
# corrupted JSON file behind — you either get the old version or the new
# one, never a broken one.

def _atomic_write_json(path: str, data: dict) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def _load_json(path: str, default: dict) -> dict:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_users() -> dict:
    return _load_json(
        USERS_FILE,
        {"authorized": [], "pending_auth_requests": {}, "_next_auth_id": 1},
    )


def save_users(data: dict) -> None:
    _atomic_write_json(USERS_FILE, data)


def load_library() -> dict:
    return _load_json(LIBRARY_FILE, {"items": {}, "_next_item_id": 1})


def save_library(data: dict) -> None:
    _atomic_write_json(LIBRARY_FILE, data)


def load_access() -> dict:
    return _load_json(
        ACCESS_FILE,
        {"grants": {}, "pending_requests": {}, "_next_request_id": 1},
    )


def save_access(data: dict) -> None:
    _atomic_write_json(ACCESS_FILE, data)


def load_wishlist() -> list:
    return _load_json(WISHLIST_FILE, {"items": []}).get("items", [])


def append_wishlist(entry: dict) -> None:
    data = _load_json(WISHLIST_FILE, {"items": []})
    data["items"].append(entry)
    _atomic_write_json(WISHLIST_FILE, data)


# ---------------------------------------------------------------------------
# Authorization helpers
# ---------------------------------------------------------------------------

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_authorized(user_id: int) -> bool:
    # Admins are always implicitly authorized — no need to also add them
    # to the authorized list.
    if is_admin(user_id):
        return True
    users = load_users()
    return user_id in users["authorized"]


def admin_only(func):
    """Decorator: silently ignore the update if the caller isn't an admin."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or not is_admin(user.id):
            if update.message:
                await update.message.reply_text("This command is for admins only.")
            return
        return await func(update, context)
    return wrapper


def authorized_only(func):
    """Decorator: politely reject the update if the caller isn't authorized."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or not is_authorized(user.id):
            if update.message:
                await update.message.reply_text(
                    "You're not authorized to use this bot yet. Send /start to request access."
                )
            elif update.callback_query:
                await update.callback_query.answer(
                    "You're not authorized to use this bot yet.", show_alert=True
                )
            return
        return await func(update, context)
    return wrapper


# ---------------------------------------------------------------------------
# Menus
# ---------------------------------------------------------------------------

def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🔍 Search Library", callback_data="menu:search")],
        [InlineKeyboardButton("📂 My Access", callback_data="menu:myaccess")],
    ]
    if is_admin(user_id):
        rows.append([InlineKeyboardButton("🛠 Pending Requests", callback_data="menu:pending")])
    return InlineKeyboardMarkup(rows)


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str = None):
    user = update.effective_user
    text = text or "What would you like to do?"
    markup = main_menu_keyboard(user.id)
    if update.message:
        await update.message.reply_text(text, reply_markup=markup)
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=markup)


# ---------------------------------------------------------------------------
# /start and Layer 1 authorization (bot-wide access)
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if is_authorized(user.id):
        await send_main_menu(update, context, f"Welcome back, {user.first_name}!")
        return

    users = load_users()
    already_pending = any(
        req["user_id"] == user.id for req in users["pending_auth_requests"].values()
    )
    if already_pending:
        await update.message.reply_text(
            "You've already requested access — an admin hasn't responded yet. "
            "Please wait, you'll be notified here as soon as they do."
        )
        return

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🙋 Request Access", callback_data="reqauth")]]
    )
    await update.message.reply_text(
        "This bot is invite-only. If you'd like access, tap below to send "
        "a request to the admins.",
        reply_markup=keyboard,
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user.id):
        await cmd_start(update, context)
        return
    await send_main_menu(update, context)


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handy for a new user to grab their own numeric ID and send it to an
    # admin, so the admin can /adduser them without waiting on a request.
    user = update.effective_user
    await update.message.reply_text(f"Your Telegram ID is: `{user.id}`", parse_mode="Markdown")


async def cb_request_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    if is_authorized(user.id):
        await query.edit_message_text("You're already authorized — send /start.")
        return

    users = load_users()

    if any(req["user_id"] == user.id for req in users["pending_auth_requests"].values()):
        await query.edit_message_text("You've already got a pending request — hang tight.")
        return

    req_id = str(users["_next_auth_id"])
    users["_next_auth_id"] += 1
    users["pending_auth_requests"][req_id] = {
        "user_id": user.id,
        "username": user.username or "",
        "name": user.full_name,
        "requested_at": datetime.now().strftime(DATE_FMT),
    }
    save_users(users)

    await query.edit_message_text("Your request has been sent to the admins. You'll be notified here once they respond.")

    admin_keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"authok:{req_id}"),
                InlineKeyboardButton("❌ Deny", callback_data=f"authno:{req_id}"),
            ]
        ]
    )
    handle = f"@{user.username}" if user.username else "(no username)"
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"🙋 New access request\n\n"
                    f"Name: {user.full_name}\n"
                    f"Username: {handle}\n"
                    f"ID: {user.id}"
                ),
                reply_markup=admin_keyboard,
            )
        except Exception as e:
            logger.warning(f"Couldn't notify admin {admin_id}: {e}")


async def cb_auth_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    admin = update.effective_user

    if not is_admin(admin.id):
        await query.answer("Admins only.", show_alert=True)
        return

    action, req_id = query.data.split(":", 1)
    users = load_users()
    req = users["pending_auth_requests"].pop(req_id, None)

    if req is None:
        await query.answer("Already handled by another admin.", show_alert=True)
        await query.edit_message_text(query.message.text + "\n\n(Already handled.)")
        return

    save_users(users)  # persist the pop immediately so a second tap can't race this one
    target_user_id = req["user_id"]

    if action == "authok":
        users = load_users()  # reload in case anything else changed it in between
        if target_user_id not in users["authorized"]:
            users["authorized"].append(target_user_id)
        save_users(users)
        await query.edit_message_text(query.message.text + f"\n\n✅ Approved by {admin.first_name}.")
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="✅ You've been granted access to the bot! Send /start to begin.",
            )
        except Exception as e:
            logger.warning(f"Couldn't notify approved user {target_user_id}: {e}")
    else:
        await query.edit_message_text(query.message.text + f"\n\n❌ Denied by {admin.first_name}.")
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="❌ Your access request was denied by an admin.",
            )
        except Exception as e:
            logger.warning(f"Couldn't notify denied user {target_user_id}: {e}")

    await query.answer()


@admin_only
async def cmd_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /adduser <telegram_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("That doesn't look like a valid numeric Telegram ID.")
        return

    users = load_users()
    if target_id in users["authorized"]:
        await update.message.reply_text("That user is already authorized.")
        return
    users["authorized"].append(target_id)
    save_users(users)
    await update.message.reply_text(f"✅ User {target_id} is now authorized.")
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text="✅ You've been granted access to the bot! Send /start to begin.",
        )
    except Exception:
        pass  # they may not have started a chat with the bot yet — that's fine


@admin_only
async def cmd_removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /removeuser <telegram_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("That doesn't look like a valid numeric Telegram ID.")
        return

    users = load_users()
    if target_id not in users["authorized"]:
        await update.message.reply_text("That user wasn't authorized to begin with.")
        return
    users["authorized"].remove(target_id)
    save_users(users)
    await update.message.reply_text(f"🚫 User {target_id} has been removed.")


@admin_only
async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    lines = ["**Admins:**"] + [f"- {a}" for a in ADMIN_IDS]
    lines.append("\n**Authorized users:**")
    if users["authorized"]:
        lines += [f"- {u}" for u in users["authorized"]]
    else:
        lines.append("(none yet)")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Library search
# ---------------------------------------------------------------------------

def _matching_items(query: str, items: dict) -> list:
    """Flexible search: a single letter browses by first letter, anything
    longer searches anywhere in the name. Both are case-insensitive."""
    query = query.strip().lower()
    results = []
    if len(query) == 1:
        for item_id, item in items.items():
            if item["name"].lower().startswith(query):
                results.append((item_id, item))
    else:
        for item_id, item in items.items():
            if query in item["name"].lower():
                results.append((item_id, item))
    results.sort(key=lambda pair: pair[1]["name"].lower())
    return results


@authorized_only
async def cmd_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "Type a single letter to browse (e.g. 'S'), or a word to search by name. /cancel to stop."
        )
    else:
        await update.message.reply_text(
            "Type a single letter to browse (e.g. 'S'), or a word to search by name. /cancel to stop."
        )
    return SEARCH_WAITING_QUERY


async def search_query_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.message.text.strip()
    if not query:
        await update.message.reply_text("Please type a letter or a word.")
        return SEARCH_WAITING_QUERY

    library = load_library()
    matches = _matching_items(query, library["items"])

    if not matches:
        context.user_data["last_search_query"] = query
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🙋 Request this file", callback_data="reqfile")]]
        )
        await update.message.reply_text(
            f"No files found matching '{query}'. If you were expecting something "
            f"specific, you can ask the admins to add it.",
            reply_markup=keyboard,
        )
        return ConversationHandler.END

    buttons = [
        [InlineKeyboardButton(f"📄 {item['name']}", callback_data=f"file:{item_id}")]
        for item_id, item in matches
    ]
    await update.message.reply_text(
        f"Found {len(matches)} result(s):", reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ConversationHandler.END


async def cmd_search_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Search cancelled.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Delivering a file / Layer 2 (per-file, time-limited access)
# ---------------------------------------------------------------------------

def _grant_key(user_id: int, item_id: str) -> str:
    return f"{user_id}:{item_id}"


def _active_grant(access: dict, user_id: int, item_id: str) -> dict | None:
    grant = access["grants"].get(_grant_key(user_id, item_id))
    if not grant:
        return None
    expires_at = datetime.strptime(grant["expires_at"], DATE_FMT)
    if expires_at < datetime.now():
        return None
    return grant


async def _deliver_file(context: ContextTypes.DEFAULT_TYPE, chat_id: int, item: dict) -> None:
    # copy_message (not forward_message) so the recipient sees it as coming
    # straight from the bot — no "Forwarded from" tag revealing the private
    # channel or chat the file was originally registered from.
    await context.bot.copy_message(
        chat_id=chat_id,
        from_chat_id=item["source_chat_id"],
        message_id=item["source_message_id"],
    )


@authorized_only
async def cb_open_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    item_id = query.data.split(":", 1)[1]

    library = load_library()
    item = library["items"].get(item_id)
    if not item:
        await query.message.reply_text("This file is no longer available.")
        return

    access = load_access()
    grant = _active_grant(access, user.id, item_id)

    if grant:
        expires_at = grant["expires_at"]
        await _deliver_file(context, user.id, item)
        await query.message.reply_text(f"✅ Here you go! Your access to this file expires {expires_at}.")
        return

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔓 Request Access", callback_data=f"reqfileaccess:{item_id}")]]
    )
    await query.message.reply_text(
        f"🔒 *{item['name']}*\n\nYou need admin approval to receive this file.",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@authorized_only
async def cb_request_file_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    item_id = query.data.split(":", 1)[1]

    library = load_library()
    item = library["items"].get(item_id)
    if not item:
        await query.message.reply_text("This file is no longer available.")
        return

    access = load_access()

    already_pending = any(
        req["user_id"] == user.id and req["item_id"] == item_id
        for req in access["pending_requests"].values()
    )
    if already_pending:
        await query.message.reply_text("You've already requested this — waiting on an admin.")
        return

    if _active_grant(access, user.id, item_id):
        await _deliver_file(context, user.id, item)
        await query.message.reply_text("You already have access — here it is again.")
        return

    req_id = str(access["_next_request_id"])
    access["_next_request_id"] += 1
    access["pending_requests"][req_id] = {
        "user_id": user.id,
        "item_id": item_id,
        "requested_at": datetime.now().strftime(DATE_FMT),
    }
    save_access(access)

    await query.message.reply_text("Your request has been sent to the admins.")

    admin_keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"fileok:{req_id}"),
                InlineKeyboardButton("❌ Deny", callback_data=f"fileno:{req_id}"),
            ]
        ]
    )
    handle = f"@{user.username}" if user.username else "(no username)"
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"🔓 File access request\n\n"
                    f"File: {item['name']}\n"
                    f"From: {user.full_name} {handle} (ID {user.id})\n"
                    f"If approved, access lasts {DEFAULT_ACCESS_DAYS} day(s)."
                ),
                reply_markup=admin_keyboard,
            )
        except Exception as e:
            logger.warning(f"Couldn't notify admin {admin_id}: {e}")


async def cb_file_access_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    admin = update.effective_user

    if not is_admin(admin.id):
        await query.answer("Admins only.", show_alert=True)
        return

    action, req_id = query.data.split(":", 1)
    access = load_access()
    req = access["pending_requests"].pop(req_id, None)

    if req is None:
        await query.answer("Already handled by another admin.", show_alert=True)
        await query.edit_message_text(query.message.text + "\n\n(Already handled.)")
        return

    save_access(access)  # persist the pop right away so a second tap can't race this one

    target_user_id = req["user_id"]
    item_id = req["item_id"]
    library = load_library()
    item = library["items"].get(item_id)
    item_name = item["name"] if item else "(deleted file)"

    if action == "fileok":
        if not item:
            await query.edit_message_text(query.message.text + "\n\n⚠️ That file was deleted before approval could complete.")
            await query.answer()
            return

        expires_at = (datetime.now() + timedelta(days=DEFAULT_ACCESS_DAYS)).strftime(DATE_FMT)
        access = load_access()  # reload in case anything else changed it
        access["grants"][_grant_key(target_user_id, item_id)] = {
            "granted_at": datetime.now().strftime(DATE_FMT),
            "expires_at": expires_at,
            "granted_by": admin.id,
        }
        save_access(access)

        await query.edit_message_text(query.message.text + f"\n\n✅ Approved by {admin.first_name}.")
        try:
            await _deliver_file(context, target_user_id, item)
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"✅ Access approved! This access expires {expires_at}.",
            )
        except Exception as e:
            logger.warning(f"Couldn't deliver file to {target_user_id}: {e}")
    else:
        await query.edit_message_text(query.message.text + f"\n\n❌ Denied by {admin.first_name}.")
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"❌ Your request for '{item_name}' was denied by an admin.",
            )
        except Exception as e:
            logger.warning(f"Couldn't notify user {target_user_id}: {e}")

    await query.answer()


@authorized_only
async def cb_request_missing_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    requested_name = context.user_data.get("last_search_query", "(unknown)")

    append_wishlist(
        {
            "name": requested_name,
            "requested_by": user.id,
            "username": user.username or "",
            "requested_at": datetime.now().strftime(DATE_FMT),
        }
    )
    await query.message.reply_text("Thanks — the admins have been notified.")

    handle = f"@{user.username}" if user.username else "(no username)"
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"🙋 {user.full_name} {handle} (ID {user.id}) searched for "
                    f"'{requested_name}' and found nothing. Consider adding it "
                    f"(forward the file to this bot to register it)."
                ),
            )
        except Exception as e:
            logger.warning(f"Couldn't notify admin {admin_id}: {e}")


@authorized_only
async def cmd_myaccess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.callback_query:
        await update.callback_query.answer()

    access = load_access()
    library = load_library()

    active = []
    for key, grant in access["grants"].items():
        uid_str, item_id = key.split(":", 1)
        if int(uid_str) != user.id:
            continue
        expires_at = datetime.strptime(grant["expires_at"], DATE_FMT)
        if expires_at < datetime.now():
            continue
        item = library["items"].get(item_id)
        if item:
            active.append(f"- {item['name']} (expires {grant['expires_at']})")

    reply_target = update.callback_query.message if update.callback_query else update.message
    if not active:
        await reply_target.reply_text("You don't have any active file access right now.")
    else:
        await reply_target.reply_text("**Your active access:**\n" + "\n".join(active), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Admin: pending requests overview
# ---------------------------------------------------------------------------

@admin_only
async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    reply_target = update.callback_query.message if update.callback_query else update.message

    users = load_users()
    access = load_access()
    library = load_library()

    if not users["pending_auth_requests"] and not access["pending_requests"]:
        await reply_target.reply_text("No pending requests right now.")
        return

    for req_id, req in users["pending_auth_requests"].items():
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"authok:{req_id}"),
                    InlineKeyboardButton("❌ Deny", callback_data=f"authno:{req_id}"),
                ]
            ]
        )
        await reply_target.reply_text(
            f"🙋 Access request\n\nName: {req['name']}\nID: {req['user_id']}",
            reply_markup=keyboard,
        )

    for req_id, req in access["pending_requests"].items():
        item = library["items"].get(req["item_id"])
        item_name = item["name"] if item else "(deleted file)"
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"fileok:{req_id}"),
                    InlineKeyboardButton("❌ Deny", callback_data=f"fileno:{req_id}"),
                ]
            ]
        )
        await reply_target.reply_text(
            f"🔓 File request\n\nFile: {item_name}\nFrom ID: {req['user_id']}",
            reply_markup=keyboard,
        )


@admin_only
async def cmd_wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = load_wishlist()[-20:]
    if not items:
        await update.message.reply_text("No file requests logged yet.")
        return
    lines = [f"- '{i['name']}' — requested by ID {i['requested_by']} on {i['requested_at']}" for i in items]
    await update.message.reply_text("**Last 20 requested-but-missing files:**\n" + "\n".join(lines), parse_mode="Markdown")


@admin_only
async def cmd_listfiles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Mainly here so an admin can look up a file's ID before using /rename —
    # the ID isn't shown anywhere else during normal day-to-day use.
    library = load_library()
    items = library["items"]
    if not items:
        await update.message.reply_text("The library is empty — forward a file to the bot to add one.")
        return
    lines = [
        f"#{item_id} — {item['name']}"
        for item_id, item in sorted(items.items(), key=lambda pair: pair[1]["name"].lower())
    ]
    # Telegram caps messages at 4096 characters — chunk the list so a large
    # library doesn't silently fail to send.
    chunk = []
    length = 0
    for line in lines:
        if length + len(line) + 1 > 3500:
            await update.message.reply_text("\n".join(chunk))
            chunk, length = [], 0
        chunk.append(line)
        length += len(line) + 1
    if chunk:
        await update.message.reply_text("\n".join(chunk))


@admin_only
async def cmd_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /rename <id> <new name>\n\nUse /listfiles to find a file's ID."
        )
        return

    item_id = context.args[0]
    new_name = " ".join(context.args[1:]).strip()
    if not new_name:
        await update.message.reply_text("The new name can't be empty.")
        return

    library = load_library()
    item = library["items"].get(item_id)
    if not item:
        await update.message.reply_text(f"No file with ID #{item_id}. Use /listfiles to check.")
        return

    old_name = item["name"]
    item["name"] = new_name
    save_library(library)
    # Renaming only ever changes what the file is called and searched by —
    # the underlying file_id/source message, and everyone's existing access
    # grants for this item_id, are untouched.
    await update.message.reply_text(f"✅ Renamed '{old_name}' → '{new_name}' (#{item_id}).")


# ---------------------------------------------------------------------------
# Admin: registering a new file (forward the file to the bot to start)
# ---------------------------------------------------------------------------

@admin_only
async def addfile_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message

    if message.document:
        file_id = message.document.file_id
        file_type = "document"
    elif message.video:
        file_id = message.video.file_id
        file_type = "video"
    elif message.audio:
        file_id = message.audio.file_id
        file_type = "audio"
    elif message.voice:
        file_id = message.voice.file_id
        file_type = "voice"
    elif message.photo:
        file_id = message.photo[-1].file_id  # largest resolution
        file_type = "photo"
    else:
        return ConversationHandler.END  # not a file type we handle

    context.user_data["pending_file"] = {
        "file_id": file_id,
        "file_type": file_type,
        "source_chat_id": message.chat_id,
        "source_message_id": message.message_id,
    }
    await message.reply_text(
        "Got the file! What name should this be listed under? "
        "(this is exactly what users will search for — /cancel to stop)"
    )
    return ADD_FILE_WAITING_NAME


async def addfile_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Please type a name.")
        return ADD_FILE_WAITING_NAME

    pending = context.user_data.pop("pending_file", None)
    if not pending:
        await update.message.reply_text("Something went wrong — please forward the file again.")
        return ConversationHandler.END

    library = load_library()
    item_id = str(library["_next_item_id"])
    library["_next_item_id"] += 1
    library["items"][item_id] = {
        "name": name,
        "file_type": pending["file_type"],
        "source_chat_id": pending["source_chat_id"],
        "source_message_id": pending["source_message_id"],
        "added_by": update.effective_user.id,
        "added_at": datetime.now().strftime(DATE_FMT),
    }
    save_library(library)

    await update.message.reply_text(f"✅ Added '{name}' to the library (ID #{item_id}).")
    return ConversationHandler.END


async def addfile_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("pending_file", None)
    await update.message.reply_text("Cancelled — file was not added.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Fallback for anything else
# ---------------------------------------------------------------------------

async def fallback_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user.id):
        await cmd_start(update, context)
        return
    await update.message.reply_text("Not sure what you mean — send /menu to see your options.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # --- Search conversation ---
    search_conv = ConversationHandler(
        entry_points=[
            CommandHandler("search", cmd_search_start),
            CallbackQueryHandler(cmd_search_start, pattern="^menu:search$"),
        ],
        states={
            SEARCH_WAITING_QUERY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_query_received)
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_search_cancel)],
    )

    # --- Add-file conversation (admin forwards a file to start) ---
    addfile_conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.User(user_id=ADMIN_IDS)
                & (
                    filters.Document.ALL
                    | filters.VIDEO
                    | filters.AUDIO
                    | filters.VOICE
                    | filters.PHOTO
                ),
                addfile_received,
            )
        ],
        states={
            ADD_FILE_WAITING_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, addfile_name_received)
            ],
        },
        fallbacks=[CommandHandler("cancel", addfile_cancel)],
    )

    # Handler order matters here: python-telegram-bot runs only the first
    # matching handler in a group, no fallthrough. Both ConversationHandlers
    # must be registered before the generic fallback_text handler, or their
    # first message (e.g. a forwarded file, or a typed search query) could
    # get swallowed by the catch-all instead.
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CommandHandler("adduser", cmd_adduser))
    app.add_handler(CommandHandler("removeuser", cmd_removeuser))
    app.add_handler(CommandHandler("listusers", cmd_listusers))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("wishlist", cmd_wishlist))
    app.add_handler(CommandHandler("listfiles", cmd_listfiles))
    app.add_handler(CommandHandler("rename", cmd_rename))
    app.add_handler(CommandHandler("myaccess", cmd_myaccess))

    app.add_handler(search_conv)
    app.add_handler(addfile_conv)

    app.add_handler(CallbackQueryHandler(cb_request_auth, pattern="^reqauth$"))
    app.add_handler(CallbackQueryHandler(cb_auth_decision, pattern="^auth(ok|no):"))
    app.add_handler(CallbackQueryHandler(cb_open_file, pattern="^file:"))
    app.add_handler(CallbackQueryHandler(cb_request_file_access, pattern="^reqfileaccess:"))
    app.add_handler(CallbackQueryHandler(cb_file_access_decision, pattern="^file(ok|no):"))
    app.add_handler(CallbackQueryHandler(cb_request_missing_file, pattern="^reqfile$"))
    app.add_handler(CallbackQueryHandler(cmd_myaccess, pattern="^menu:myaccess$"))
    app.add_handler(CallbackQueryHandler(cmd_pending, pattern="^menu:pending$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_text))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
