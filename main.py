# ==============================
# ⚙️ CONFIGURATION (EDIT BELOW)
# ==============================

BOT_TOKEN = "8222403305:AAHJ9ewwYYNa3lWFm3fZhgBplCP65e6g054"  # <- @BotFather se liya hua token

# Sender (jo IP list daalega)
SENDER_ID = 7259707610  # <- yahan apna Telegram numeric ID daalo (e.g. 570123456)

# Receivers (jinhe har 7 min me IPs milenge)
RECEIVER_IDS = [
    8397270065,  # <- Receiver 1 ID
    222222222,  # <- Receiver 2 ID
    # aur chaho to aur bhi add karo
    # 333333333,
    # 444444444,
]

# Time interval (seconds me) — default 7 minutes
DROP_INTERVAL = 6 * 60

# ==============================
# 🚀 BOT CODE (DON'T TOUCH BELOW)
# ==============================

import time, threading
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

ip_queue = []
sending = False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 AutoDrop Bot Ready!\n\nCommands:\n"
        "/push (paste IPs below)\n"
        "/pull (start sending to receivers)"
    )


async def push(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ip_queue
    user_id = update.effective_user.id

    if user_id != SENDER_ID:
        await update.message.reply_text("❌ You are not authorized to push.")
        return

    # remove /push line, keep remaining lines as IPs
    lines = update.message.text.split("\n")[1:]
    new_ips = [line.strip() for line in lines if line.strip()]

    if not new_ips:
        await update.message.reply_text("⚠️ No IPs found in message.")
        return

    ip_queue.extend(new_ips)
    await update.message.reply_text(f"✅ Added {len(new_ips)} IPs to queue.")


async def pull(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global sending
    user_id = update.effective_user.id

    if user_id != SENDER_ID:
        await update.message.reply_text("❌ Only sender can start sending.")
        return

    if not ip_queue:
        await update.message.reply_text("⚠️ No IPs in queue.")
        return

    if sending:
        await update.message.reply_text("⏳ Already sending.")
        return

    await update.message.reply_text(f"🚀 Started sending IPs to {len(RECEIVER_IDS)} receivers every 7 min.")
    sending = True
    threading.Thread(target=send_ips, args=(context,)).start()


def send_ips(context):
    global sending, ip_queue
    app = context.application

    while ip_queue:
        ip = ip_queue.pop(0)
        for rid in RECEIVER_IDS:
            try:
                app.create_task(app.bot.send_message(chat_id=rid, text=ip))
            except Exception as e:
                print(f"⚠️ Failed to send to {rid}: {e}")
        time.sleep(DROP_INTERVAL)

    sending = False
    for rid in RECEIVER_IDS:
        try:
            app.create_task(app.bot.send_message(chat_id=rid, text="✅ Done"))
        except Exception:
            pass


if name == "main":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex(r"^/push"), push))
    app.add_handler(CommandHandler("pull", pull))

    print("🤖 Bot running...")
    app.run_polling()
