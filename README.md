# File Library Bot

A Telegram bot for privately distributing files. Only pre-approved users
can use it at all, and even then, every individual file needs a separate,
time-limited admin approval before it's sent.

Built with [`python-telegram-bot`](https://github.com/python-telegram-bot/python-telegram-bot) (async/await style, v22.x).

---

## Why this exists

**My Case** - I wanted to provide notes and study materials to my juniors and college-mates. But due to some various reason, not all of them got the materials and notes on time. This made me look for a option to provide them access to a system where they can first, identify themselves and then ask for authorization to access files from the bot.

- **Why I needed this? Won't it be efficient to hand them notes on your own?** Can work but I didn't want to handle multiple calls and messages at a time to just do that. I had my own classes and work to do.
- **Why I needed authorization for each file?** To avoid wasting resources and only provide related materials. Some students hoarde materials with them even if they don't need it and usually those students won't even share them that's why this authorization wall was needed.
- **What problem(s) did it solve?** It actually solved two problems - First, that I didn't need to give notes and stuff on my own, the admins would handle it. Second, I didn't have to bother for storage issues as all of the data is stored on Telegram.


Telegram bots are publicly discoverable - anyone who finds the bot's
username can open a chat with it. This bot is built so that doesn't
matter:

1. **Layer 1 - bot-wide authorization.** Nobody can search or request
   anything until an admin has explicitly authorized their Telegram ID,
   either in advance (`/adduser`) or by approving a request they send
   through the bot.
2. **Layer 2 - per-file, time-limited access.** Being authorized to use
   the bot doesn't mean a user can pull any file whenever they like. Each
   file request needs its own admin approval, and access to that specific
   file automatically expires after a set number of days
   (`DEFAULT_ACCESS_DAYS` in `config.py`, default 7). This keeps files
   from just sitting permanently unlocked for people who only needed them
   once.

Any number of admins can approve or deny requests. Whichever admin taps
first wins - the request is removed the instant it's handled, so two
admins can't both act on the same one.

---

## How files are stored and delivered

Files are **never** downloaded or stored on the machine running this bot.

1. You keep your files organized in a private Telegram channel (or
   anywhere else you like - a private chat works too).
2. To register a file with the bot, **forward it to the bot directly**
   (as an admin). The bot asks what name it should be listed under -
   that's exactly what users will search for - and remembers the file's
   Telegram `file_id` plus where it came from.
   **To tackle the problem of naming bulk files and large files, it can also index files from the chat/channel/group on Telegram as well.**
3. When a user is approved for a file, the bot delivers it using
   `copy_message`, **not** a forward. A real forward would show
   "Forwarded from [Channel Name]" and leak the existence/name of your
   private source channel to the recipient. A copy looks like it came
   straight from the bot - the source stays completely hidden.
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
the search term to `wishlist.json` and notifies every admin - so you
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

### 🗂 Automatic daily backup
Since the bot runs permanently on one device, `users.json`, `library.json`,
`access.json`, `wishlist.json`, and `admins.json` (whichever currently
exist) get zipped up and sent straight to **one specific Telegram ID** -
`BACKUP_RECIPIENT_ID` in `config.py` (defaults to the first ID in
`ADMIN_IDS` if you don't set it) - once a day, automatically. Deliberately
**not** broadcast to every admin - this data is sensitive, so it goes to
just you (the intended admin). No manual copying, no server to set up. Defaults to 11:59 PM
India time; the time, timezone, and recipient are all configurable in
`config.py` (see `config_example.py`). This is purely a safety net and a
way to check current data from any other device - it's just an ordinary
file attachment in a normal Telegram chat, nothing to run or install on
the receiving end.

You can also trigger this on demand anytime with `/backup` (any admin can
run the command, but the file always goes to `BACKUP_RECIPIENT_ID`, not
whoever ran it), without waiting for the scheduled time.

### 🛠 Admin tools
- `/pending` - re-lists every outstanding access and file request with
  fresh Approve/Deny buttons, in case the original notification scrolled
  out of view.
- `/wishlist` - the last 20 file requests that came up empty in search,
  so you know what to add.
- `/listusers` - shows config-file admins, runtime-added admins, and all
  currently authorized users, in three separate lists.
- `/removeuser <telegram_id>` - revokes bot-wide access.
- `/addadmin <telegram_id>` / `/removeadmin <telegram_id>` - promote or
  demote an admin on the fly, no restart needed. (Admins listed in
  `config.py` can't be removed this way on purpose - that's still a
  config-file-and-restart change, so there's always at least one admin
  who can't accidentally be locked out by another admin.)
- `/listfiles` - lists every file's ID and name.
- `/rename <id> <new name>` - fixes a wrong name without touching the
  file or anyone's access.
- `/deletefile <id>` - removes a file from the library (and cleans up any
  access grants/requests pointing at it). IDs are **never** reused - the
  library's ID counter only ever counts up, so a deleted file's ID stays
  retired forever and can't collide with anything added later.
- **Adding a file - two ways:**
  - **Manual:** forward it to the bot in a private chat; it'll ask for a
    name and add it.
  - **Automatic (channel auto-indexing):** make the bot an admin of a
    private channel, set `AUTO_INDEX_CHANNEL_ID` in `config.py` to that
    channel's ID, and restart. From then on, every file posted to that
    channel is registered automatically - using the post's caption as the
    name (or the original filename if there's no caption). Every admin
    gets a notification when this happens, with the assigned ID, in case
    the auto-picked name needs a `/rename`.
  - **Finding a channel's ID:** if you make the bot an admin of a channel
    but haven't set `AUTO_INDEX_CHANNEL_ID` yet, the bot will message
    every admin with that channel's numeric ID the first time it sees a
    post there - copy that straight into `config.py`.

---

## Requirements

- Python 3.10+
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Your own Telegram numeric ID (from `/myid` once the bot is running, or
  [@userinfobot](https://t.me/userinfobot)) to put in `ADMIN_IDS`

### Python packages

```bash
pip install python-telegram-bot --upgrade
pip install tzdata
```

`tzdata` is needed for the daily backup's timezone handling
(`BACKUP_TIMEZONE`, e.g. `"Asia/Kolkata"`) to actually resolve. **This is
mainly a Windows requirement** - Windows doesn't ship the IANA timezone
database that Python's `zoneinfo` relies on, so without this package
you'll get an error saying the timezone can't be found. Linux/Termux
usually already has system timezone data, but installing it there too
doesn't hurt.

---

## Setup

1. **Clone the repo**
   ```bash
   git clone https://github.com/ImPriyanshPandey/File-Library-Bot
   cd File-Library-Bot
   ```

2. **Install dependencies** (see above).

3. **Create `config.py`** - copy `config_example.py` and fill in your
   real values.
   ```bash
   copy config_example.py config.py
   ```
   ```python
   BOT_TOKEN = "your-bot-token-from-botfather"
   ADMIN_IDS = [111111111]        # list - supports multiple admins
   DEFAULT_ACCESS_DAYS = 7
   #AUTO_INDEX_CHANNEL_ID = -1234567890 - use it for auto-indexing if needed.
   #BACKUP_HOUR = 23 - use it for backup option of library, access, wishlist, user data (.json) files.
   # BACKUP_MINUTE = 59
   # BACKUP_TIMEZONE = "Asia/Kolkata" - you can change the time zone and time details however you like to do the backup.
   ```

4. **Run the bot:**
   ```bash
   python bot.py
   ```
   Keep the terminal window open - the bot runs via long polling. Stop
   it with `Ctrl+C`.

5. **Add yourself as the first admin** - put your own Telegram ID in
   `ADMIN_IDS` in `config.py` before starting the bot; admins don't need
   to go through `/adduser`.

6. **Add your first file** - as an admin, forward any document, video,
   audio, voice note, or photo to the bot in a private chat, then type
   the name it should be searchable by.

---

## Project Structure

```
.
├── bot.py                 # Main bot script
├── config.py               # Secrets/config - NOT committed (see .gitignore)
├── config_example.py       # Template for config.py
├── users.json              # Auto-generated - authorized users + pending access requests
├── library.json             # Auto-generated - file entries (name, file_id, source location)
├── access.json              # Auto-generated - per-user-per-file grants (with expiry) + pending file requests
├── wishlist.json            # Auto-generated - log of searches that found nothing
├── admins.json              # Auto-generated - admins added at runtime via /addadmin
└── .gitignore
```

All five `.json` files are created automatically the first time they're
needed - you don't need to create them by hand. Every write to them goes
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
| `/addadmin <id>` | admin | Promotes a user to admin, effective immediately |
| `/removeadmin <id>` | admin | Demotes a runtime-added admin (config.py admins aren't removable this way) |
| `/listusers` | admin | Lists config-file admins, runtime-added admins, and authorized users separately |
| `/pending` | admin | Re-shows every outstanding request with Approve/Deny buttons |
| `/wishlist` | admin | Shows the last 20 "not found" searches |
| `/listfiles` | admin | Lists every file's ID and current name - use this to find the ID for `/rename` or `/deletefile` |
| `/rename <id> <new name>` | admin | Fixes a file's name if it was entered wrong (doesn't touch the file itself or anyone's existing access) |
| `/deletefile <id>` | admin | Removes a file from the library. IDs are never reused. |
| `/backup` | admin | Sends a zip of the current data files to `BACKUP_RECIPIENT_ID` right now, instead of waiting for the scheduled daily one |

---

## A Note on Handler Order

`python-telegram-bot` only runs the **first matching handler** per
update - there's no fallthrough. Both the search flow and the add-file
flow are registered *before* the generic catch-all text handler, so a
typed search query or a forwarded file always gets caught by the right
flow first. If you add new handlers, keep this ordering in mind - see
the comment above the handler registration block in `bot.py`.

---

## Running on Android (Termux)

Since the bot only needs outbound internet (long-polling, no inbound ports), it can run from a phone too - handy when your PC isn't always on. Quick version:

1. Install **Termux** from [F-Droid](https://f-droid.org/packages/com.termux/) - not the Play Store (outdated there). Only install "Termux" itself for this; the Termux:API/Float/Widget/etc. add-ons aren't needed.
2. `termux-setup-storage` (grants access to phone storage, e.g. Downloads).
3. `pkg install python git -y`
4. `git clone https://github.com/ImPriyanshPandey/File-Library-Bot` then `cd File-Library-Bot`
5. Create `config.py` on the phone the same way as on PC (`nano config.py`, paste in your real values, `Ctrl+O` → Enter → `Ctrl+X` to save).
6. `pip install python-telegram-bot --upgrade`
7. Test it: `python bot.py` - confirm `/start` responds, then `Ctrl+C`.
8. Keep it running after closing the terminal:
   ```bash
   termux-wake-lock
   nohup python bot.py > bot.log 2>&1 &
   ```
9. **Settings → Apps → Termux → Battery → No restrictions** - Android will otherwise kill the background process. Some phone brands (Xiaomi, Oppo, Vivo, OnePlus, etc.) need an extra "autostart" toggle too - check [dontkillmyapp.com](https://dontkillmyapp.com) for your model.
10. Optional: install **Termux:Boot** (also F-Droid) to auto-restart the bot if the phone reboots.

**Important:** `library.json`, `users.json`, `access.json`, `wishlist.json`, and `admins.json` are runtime data, not code - they don't come along with `git clone` (they're git-ignored on purpose) and don't sync between devices automatically. Only run the bot from **one device at a time** (Telegram allows just one active connection per bot token). If you do ever need to move which device is "live," the daily backup (see above) or a manual `/backup` gives you an up-to-date zip of everything to carry over.

---

## Known limitations / things to keep in mind

- **Channel auto-indexing only watches one channel at a time** -
  `AUTO_INDEX_CHANNEL_ID` holds a single channel ID. If you want files
  organized across multiple source channels, either point different
  channels at the bot manually (forward-to-add still always works
  everywhere) or extend `AUTO_INDEX_CHANNEL_ID` into a list later.
- **Expiry is checked lazily**, at the moment a user tries to open a
  file - there's no background job clearing out expired grants. This is
  fine functionally (an expired grant is just treated as "no access"),
  but `access.json` will accumulate old expired entries over time rather
  than auto-deleting them. Not a problem at small scale.

---

## Roadmap ideas (not built yet)
- [ ] Fix the expired entries problem - the bot currently doesn't clear out expired grants entries, which can accumulate after a period of time. This can cause problem if it is scaled or have multiple users accessing it everyday.
- [ ] Optional per-file custom expiry (currently one global default for everyone) - this is what I'm thinking as not all files are of same value or need same level of access-time.
- [ ] Support multiple auto-index channels instead of just one - currently only 1 channel auto-indexing works, on bigger scale it can fail.
- [ ] Move to a genuine always-on host for true 24/7 uptime - Termux works for small scale or personal project scale, but to make bot 24/7 accessible without any device will need server availability. This can be done but is currently at last of what I want to do in the future.

---

## License

No license needed, this is made with the help of AI and my own learnings.