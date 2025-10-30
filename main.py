# ==============================
# ⚙️ CONFIG (HARDCODED)
# ==============================

BOT_TOKEN = "8222403305:AAHJ9ewwYYNa3lWFm3fZhgBplCP65e6g054"
SENDER_ID = 7259707610  # authorized sender
RECEIVER_IDS = [
    8397270065,7775543235
    222222222,
]
DROP_INTERVAL = 6 * 60  # seconds

# ==============================
# 🚀 BOT CODE (PTB v21+)
# ==============================

import asyncio
import logging
from typing import List

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Logging
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("autodrop")

ip_queue: List[str] = []
sending_task: asyncio.Task | None = None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text(
            "👋 AutoDrop Bot Ready!\n\nCommands:\n"
            "/push (paste IPs in next lines)\n"
            "/pull (start timed sending)\n"
            "/stop (cancel sending)\n"
            "/status (queue + sending state)\n"
            "/whoami (debug IDs)"
        )
    except Exception as e:
        log.exception("start handler error: %s", e)


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = update.effective_user.id if update.effective_user else None
        cid = update.effective_chat.id if update.effective_chat else None
        await update.message.reply_text(f"user_id={uid}\nchat_id={cid}")
    except Exception as e:
        log.exception("whoami handler error: %s", e)


def extract_ips_from_push(text: str) -> List[str]:
    lines = (text or "").splitlines()
    # Drop the first line (/push ...)
    ips = [ln.strip() for ln in lines[1:] if ln.strip()]
    return ips


async def push(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = update.effective_user.id if update.effective_user else None
        if uid != SENDER_ID:
            await update.message.reply_text("❌ You are not authorized to push.")
            return

        ips = extract_ips_from_push(update.message.text or "")
        if not ips:
            await update.message.reply_text("⚠️ No IPs found in message.")
            return

        ip_queue.extend(ips)
        await update.message.reply_text(f"✅ Added {len(ips)} IPs to queue.")
        log.info("PUSH by %s: +%d, queue=%d", uid, len(ips), len(ip_queue))
    except Exception as e:
        log.exception("push handler error: %s", e)
        await update.message.reply_text("❌ Push failed due to an internal error.")


async def _drain_queue_loop(app: Application):
    """
    Background loop: after initial send (already done by pull),
    continue sending one IP per interval to all receivers until queue empty.
    """
    try:
        while ip_queue:
            await asyncio.sleep(DROP_INTERVAL)
            ip = ip_queue.pop(0)
            for rid in RECEIVER_IDS:
                try:
                    await app.bot.send_message(chat_id=rid, text=ip)
                except Exception as e:
                    log.warning("Send fail to %s: %s", rid, e)
        # Completion notice
        for rid in RECEIVER_IDS:
            try:
                await app.bot.send_message(chat_id=rid, text="✅ Done")
            except Exception:
                pass
    except asyncio.CancelledError:
        log.info("Background loop cancelled.")
        # Optional: notify receivers that sending was stopped
        for rid in RECEIVER_IDS:
            try:
                await app.bot.send_message(chat_id=rid, text="⛔ Stopped")
            except Exception:
                pass
        raise
    except Exception as e:
        log.exception("Background loop error: %s", e)


async def pull(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        global sending_task
        uid = update.effective_user.id if update.effective_user else None
        if uid != SENDER_ID:
            await update.message.reply_text("❌ Only sender can start sending.")
            return

        if not ip_queue:
            await update.message.reply_text("⚠️ No IPs in queue.")
            return

        # Prevent duplicate runs
        if sending_task and not sending_task.done():
            await update.message.reply_text("⏳ Already sending.")
            return

        # Immediately send the first IP before starting the timed loop
        first_ip = ip_queue.pop(0)
        for rid in RECEIVER_IDS:
            try:
                await context.bot.send_message(chat_id=rid, text=first_ip)
            except Exception as e:
                log.warning("Initial send fail to %s: %s", rid, e)

        await update.message.reply_text(
            f"🚀 Sending started. First IP sent now. Next IP every {DROP_INTERVAL} sec."
        )

        # Start background loop to drain the rest at interval
        sending_task = context.application.create_task(_drain_queue_loop(context.application))
        log.info("PULL by %s: started loop, queue=%d", uid, len(ip_queue))
    except Exception as e:
        log.exception("pull handler error: %s", e)
        await update.message.reply_text("❌ Pull failed due to an internal error.")


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        global sending_task
        uid = update.effective_user.id if update.effective_user else None
        if uid != SENDER_ID:
            await update.message.reply_text("❌ Only sender can stop sending.")
            return

        if sending_task and not sending_task.done():
            sending_task.cancel()
            try:
                await sending_task
            except asyncio.CancelledError:
                pass
            sending_task = None
            await update.message.reply_text("🛑 Sending cancelled.")
            log.info("STOP by %s: cancelled background loop", uid)
        else:
            await update.message.reply_text("ℹ️ No active sending to stop.")
    except Exception as e:
        log.exception("stop handler error: %s", e)
        await update.message.reply_text("❌ Stop failed due to an internal error.")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        in_progress = sending_task is not None and not sending_task.done()
        await update.message.reply_text(
            f"📦 Queue: {len(ip_queue)} IPs\n"
            f"🚚 Sending: {'Yes' if in_progress else 'No'}\n"
            f"👥 Receivers: {len(RECEIVER_IDS)}"
        )
    except Exception as e:
        log.exception("status handler error: %s", e)


def main():
    try:
        import telegram
        log.info("python-telegram-bot = %s", telegram.__version__)
    except Exception:
        pass

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start, block=False))
    app.add_handler(CommandHandler("whoami", whoami, block=False))
    app.add_handler(CommandHandler("pull", pull, block=False))
    app.add_handler(CommandHandler("stop", stop_cmd, block=False))
    app.add_handler(CommandHandler("status", status_cmd, block=False))
    app.add_handler(MessageHandler(filters.Regex(r"^/push"), push, block=False))

    log.info("🤖 Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()

