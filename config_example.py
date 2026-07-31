# Copy this file to config.py and fill in your real values.
# config.py itself is git-ignored — never commit your real token/IDs.

BOT_TOKEN = "your-bot-token-from-botfather"

# List of Telegram numeric IDs who are admins. Any admin can:
#   - approve/deny access requests (Layer 1)
#   - approve/deny file requests (Layer 2)
#   - register new files (by forwarding them to the bot)
#   - use /adduser, /removeuser, /listusers, /pending, /wishlist
ADMIN_IDS = [111111111]

# How many days a user keeps access to a file after an admin approves
# their request. After this, they'll need to request that file again.
DEFAULT_ACCESS_DAYS = 7

# Optional. Leave commented out / omitted until you're ready to use it.
# Once you make the bot an admin of a private channel, run the bot and post
# any file to that channel — it'll message every admin with the channel's
# numeric ID. Paste that ID here (it looks like -100XXXXXXXXXX) and restart
# the bot to turn on auto-indexing: every file posted there from then on
# gets added to the library automatically, no manual forwarding needed.
# AUTO_INDEX_CHANNEL_ID = -1001234567890

# Optional — controls the automatic daily backup (see README). All three
# have sensible defaults built in already, so you don't need to add these
# lines unless you want a different time or timezone than 11:59 PM India time.
# BACKUP_HOUR = 23
# BACKUP_MINUTE = 59
# BACKUP_TIMEZONE = "Asia/Kolkata"

# Optional — who actually receives the backup. Defaults to the first ID in
# ADMIN_IDS if you don't set this. Deliberately sent to just ONE person,
# not every admin — this data is sensitive, so set this explicitly to your
# own Telegram ID if it's different from ADMIN_IDS[0].
# BACKUP_RECIPIENT_ID = 111111111
