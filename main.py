# main.py
BOT_TOKEN = "8222403305:AAHJ9ewwYYNa3lWFm3fZhgBplCP65e6g054"
SENDER_ID = 7259707610
RECEIVER_IDS = [8397270065, 222222222]
DROP_INTERVAL = 6 * 60

import asyncio
from typing import List
from telegram import Update
from telegram.ext import ApplicationBuilder, Application, CommandHandler, MessageHandler, ContextTypes, filters

ip_queue: List[str] = []
sending_task: asyncio.Task | None = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 AutoDrop Bot Ready!\n\nCommands:\n"
        "/push (paste IPs in next lines)\n"
        "/pull (start timed sending)\n"
        "/status (queue + sending state)"
    )

def extract_ips_from_push(text: str) -> List[str]:
    lines = text.splitlines()[1:]
    return [ln.strip() for ln in lines if ln.strip()]

async def push(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != SENDER_ID:
        await update.message.reply_text("❌ You are not authorized to push.")
        return
    ips = extract_ips_from_push(update.message.text or "")
    if not ips:
        await update.message.reply_text("⚠️ No IPs found in message.")
        return
    ip_queue.extend(ips)
    await update.message.reply_text(f"✅ Added {len(ips)} IPs to queue.")

async def _send_loop(app: Application):
    try:
        while ip_queue:
            ip = ip_queue.pop(0)
            for rid in RECEIVER_IDS:
                try:
                    await app.bot.send_message(chat_id=rid, text=ip)
                except Exception as e:
                    print(f"⚠️ Failed to send to {rid}: {e}")
            await asyncio.sleep(DROP_INTERVAL)
    finally:
        for rid in RECEIVER_IDS:
            try:
                await app.bot.send_message(chat_id=rid, text="✅ Done")
            except Exception:
                pass

async def pull(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global sending_task
    if update.effective_user.id != SENDER_ID:
        await update.message.reply_text("❌ Only sender can start sending.")
        return
    if not ip_queue:
        await update.message.reply_text("⚠️ No IPs in queue.")
        return
    if sending_task and not sending_task.done():
        await update.message.reply_text("⏳ Already sending.")
        return
    await update.message.reply_text(
        f"🚀 Started sending IPs to {len(RECEIVER_IDS)} receivers every {DROP_INTERVAL} sec."
    )
    sending_task = context.application.create_task(_send_loop(context.application))

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    in_progress = sending_task is not None and not sending_task.done()
    await update.message.reply_text(
        f"📦 Queue: {len(ip_queue)} IPs\n"
        f"🚚 Sending: {'Yes' if in_progress else 'No'}\n"
        f"👥 Receivers: {len(RECEIVER_IDS)}"
    )

def main():
    print("PTB version check before build...")
    try:
        import telegram
        print("python-telegram-bot =", telegram.__version__)
    except Exception as e:
        print("PTB not importable:", e)

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pull", pull))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(MessageHandler(filters.Regex(r"^/push"), push))
    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()

