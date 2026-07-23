# File Library Bot

A Telegram bot for privately distributing files. Only pre-approved users
can use it at all, and even then, every individual file needs a separate,
time-limited admin approval before it's sent.

Built with [`python-telegram-bot`](https://github.com/python-telegram-bot/python-telegram-bot) (async/await style, v22.x).

---

## Why this exists

Telegram bots are publicly discoverable — anyone who finds the bot's
username can open a chat with it. This bot is built so that doesn't
matter:

1. **Layer 1 — bot-wide authorization.** Nobody can search or request
   anything until an admin has explicitly authorized their Telegram ID,
   either in advance (`/adduser`) or by approving a request they send
   through the bot.
2. **Layer 2 — per-file, time-limited access.** Being authorized to use
   the bot doesn't mean a user can pull any file whenever they like. Each
   file request needs its own admin approval, and access to that specific
   file automatically expires after a set number of days
   (`DEFAULT_ACCESS_DAYS` in `config.py`, default 7). This keeps files
   from just sitting permanently unlocked for people who only needed them
   once.

Any number of admins can approve or deny requests. Whichever admin taps
first wins — the request is removed the instant it's handled, so two
admins can't both act on the same one.

---

## How files are stored and delivered

Files are **never** downloaded or stored on the machine running this bot.

1. You keep your files organized in a private Telegram channel (or
   anywhere else you like — a private chat works too).
2. To register a file with the bot, **forward it to the bot directly**
   (as an admin). The bot asks what name it should be listed under —
   that's exactly what users will search for — and remembers the file's
   Telegram `file_id` plus where it came from.
3. When a user is approved for a file, the bot delivers it using
   `copy_message`, **not** a forward. A real forward would show
   "Forwarded from [Channel Name]" and leak the existence/name of your
   private source channel to the recipient. A copy looks like it came
   straight from the bot — the source stays completely hidden.
4. Telegram hosts the actual file bytes indefinitely (as long as the
   original message isn't deleted), so the bot's own storage footprint
   stays essentially zero no matter how large your library gets.

---

## Features

### 🔍 Flexible search
`/search` (or the menu button) asks for a letter or a word:
- **Single letter** → browses every file whose name starts with that
  letter (e.g. `S` → "Summer Beats Mix", "Sunset Wallpaper Pack")
- **Word or longer text** → matches anywhere in the file's name,
  case-insensitive (e.g. `beats` → "Summer Beats Mix")

No results? The user gets a **"Request this file"** button, which logs
the search term to `wishlist.json` and notifies every admin — so you
know what people are actually looking for, even if it's not in your
library yet.

### 🔐 Two-layer access control
- **Requesting bot access:** an unauthorized user who sends `/start`
  sees a **Request Access** button. Tapping it notifies every admin with
  Approve/Deny buttons.
- **Pre-authorizing someone:** an admin can skip the request entirely
  with `/adduser <telegram_id>` (get the ID via the user's own `/myid`,
  or Telegram's `@userinfobot`).
- **Requesting a specific file:** even authorized users see a 🔒 prompt
  and a **Request Access** button the first time they open a search
  result. Approval notifies every admin; once approved, the file is sent
  immediately and access is valid for `DEFAULT_ACCESS_DAYS` days.
- **`/myaccess`** shows a user every file they currently have active
  (non-expired) access to, and when each one expires.

### 🛠 Admin tools
- `/pending` — re-lists every outstanding access and file request with
  fresh Approve/Deny buttons, in case the original notification scrolled
  out of view.
- `/wishlist` — the last 20 file requests that came up empty in search,
  so you know what to add.
- `/listusers` — shows all admins and all currently authorized users.
- `/removeuser <telegram_id>` — revokes bot-wide access.
- **Adding a file:** just forward it to the bot in a private chat; the
  bot will ask for a name and add it to the library.

---

## Requirements

- Python 3.10+
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Your own Telegram numeric ID (from `/myid` once the bot is running, or
  [@userinfobot](https://t.me/userinfobot)) to put in `ADMIN_IDS`

### Python packages

```bash
pip install python-telegram-bot --upgrade
```

---

## Setup

1. **Clone the repo**
   ```bash
   git clone https://github.com/<your-username>/<your-repo>.git
   cd <your-repo>
   ```

2. **Install dependencies** (see above).

3. **Create `config.py`** — copy `config_example.py` and fill in your
   real values. This file is git-ignored; never commit it.
   ```bash
   copy config_example.py config.py
   ```
   ```python
   BOT_TOKEN = "your-bot-token-from-botfather"
   ADMIN_IDS = [111111111]        # list — supports multiple admins
   DEFAULT_ACCESS_DAYS = 7
   ```

4. **Run the bot:**
   ```bash
   python bot.py
   ```
   Keep the terminal window open — the bot runs via long polling. Stop
   it with `Ctrl+C`.

5. **Add yourself as the first admin** — put your own Telegram ID in
   `ADMIN_IDS` in `config.py` before starting the bot; admins don't need
   to go through `/adduser`.

6. **Add your first file** — as an admin, forward any document, video,
   audio, voice note, or photo to the bot in a private chat, then type
   the name it should be searchable by.

---

## Project Structure

```
.
├── bot.py                 # Main bot script
├── config.py               # Secrets/config — NOT committed (see .gitignore)
├── config_example.py       # Template for config.py
├── users.json              # Auto-generated — authorized users + pending access requests
├── library.json             # Auto-generated — file entries (name, file_id, source location)
├── access.json              # Auto-generated — per-user-per-file grants (with expiry) + pending file requests
├── wishlist.json            # Auto-generated — log of searches that found nothing
└── .gitignore
```

All four `.json` files are created automatically the first time they're
needed — you don't need to create them by hand. Every write to them goes
through an atomic write-then-rename, so a crash or power loss mid-save
can't corrupt any of them.

---

## Commands

| Command | Who | Description |
|---|---|---|
| `/start` | anyone | Shows the menu, or a Request Access button if not authorized |
| `/menu` | authorized | Shows the main menu |
| `/myid` | anyone | Replies with your own Telegram ID (send this to an admin to get pre-authorized) |
| `/search` | authorized | Search the library by letter or word |
| `/myaccess` | authorized | Lists your currently active (non-expired) file access |
| `/cancel` | anyone mid-flow | Cancels a search or a file-add in progress |
| `/adduser <id>` | admin | Pre-authorizes a user without waiting for a request |
| `/removeuser <id>` | admin | Revokes a user's bot-wide access |
| `/listusers` | admin | Lists all admins and authorized users |
| `/pending` | admin | Re-shows every outstanding request with Approve/Deny buttons |
| `/wishlist` | admin | Shows the last 20 "not found" searches |
| `/listfiles` | admin | Lists every file's ID and current name — use this to find the ID for `/rename` |
| `/rename <id> <new name>` | admin | Fixes a file's name if it was entered wrong (doesn't touch the file itself or anyone's existing access) |

---

## A Note on Handler Order

`python-telegram-bot` only runs the **first matching handler** per
update — there's no fallthrough. Both the search flow and the add-file
flow are registered *before* the generic catch-all text handler, so a
typed search query or a forwarded file always gets caught by the right
flow first. If you add new handlers, keep this ordering in mind — see
the comment above the handler registration block in `bot.py`.

---

## Running on Android (Termux)

Since the bot only needs outbound internet (long-polling, no inbound ports), it can run from a phone too — handy when your PC isn't always on. Quick version:

1. Install **Termux** from [F-Droid](https://f-droid.org/packages/com.termux/) — not the Play Store (outdated there). Only install "Termux" itself for this; the Termux:API/Float/Widget/etc. add-ons aren't needed.
2. `termux-setup-storage` (grants access to phone storage, e.g. Downloads).
3. `pkg install python git -y`
4. `git clone https://github.com/<you>/<repo>.git` then `cd <repo>`
5. Create `config.py` on the phone the same way as on PC (`nano config.py`, paste in your real values, `Ctrl+O` → Enter → `Ctrl+X` to save).
6. `pip install python-telegram-bot --upgrade`
7. Test it: `python bot.py` — confirm `/start` responds, then `Ctrl+C`.
8. Keep it running after closing the terminal:
   ```bash
   termux-wake-lock
   nohup python bot.py > bot.log 2>&1 &
   ```
9. **Settings → Apps → Termux → Battery → No restrictions** — Android will otherwise kill the background process. Some phone brands (Xiaomi, Oppo, Vivo, OnePlus, etc.) need an extra "autostart" toggle too — check [dontkillmyapp.com](https://dontkillmyapp.com) for your model.
10. Optional: install **Termux:Boot** (also F-Droid) to auto-restart the bot if the phone reboots.

**Important:** `library.json`, `users.json`, `access.json`, and `wishlist.json` are runtime data, not code — they don't come along with `git clone` (they're git-ignored on purpose) and don't sync between devices automatically. Only run the bot from **one device at a time** (Telegram allows just one active connection per bot token), and manually copy those four JSON files over whenever you switch which device is "live."

---

## Known limitations / things to keep in mind

- **A bot can't add itself to a private channel automatically** — if you
  want the bot to auto-index everything posted to a channel, you'd need
  to add it as a channel admin and build that separately. Right now,
  registering a file is a manual one-time forward — simple, and it works
  identically whether your source is a channel, a group, or your own
  saved messages.
- **`ADMIN_IDS` is read once at startup** from `config.py`. Adding a new
  admin means editing `config.py` and restarting the bot — admins aren't
  managed the same dynamic way as regular authorized users.
- **Expiry is checked lazily**, at the moment a user tries to open a
  file — there's no background job clearing out expired grants. This is
  fine functionally (an expired grant is just treated as "no access"),
  but `access.json` will accumulate old expired entries over time rather
  than auto-deleting them. Not a problem at small scale.

---

## Roadmap ideas (not built yet)

- [ ] Auto-index a channel's posts if the bot is made an admin there,
      instead of requiring a manual forward per file
- [ ] Let admins be added/removed at runtime instead of only via `config.py`
- [ ] Optional per-file custom expiry (currently one global default for everyone)
- [ ] Move to a genuine always-on host for true 24/7 uptime — Termux on Android works as a stopgap (see above), but Oracle Cloud's "Always Free" tier (a real, permanent free Linux VM) is the actual long-term answer; Railway's free tier no longer exists as of mid-2025

---

## License

No license specified yet — add one (e.g. MIT) if you plan to make this repo public.
