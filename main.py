#!/usr/bin/env python3
"""
Dynamic AutoDrop Bot - Advanced Version
- Dynamic sender/receiver registration
- Individual IP distribution (no conflicts)
- User management panel
- Private DM system
"""

import asyncio
import json
import logging
import os
from typing import Dict, List, Set, Optional
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ==============================
# 🔧 CONFIGURATION
# ==============================

BOT_TOKEN = "8222403305:AAHJ9ewwYYNa3lWFm3fZhgBplCP65e6g054"
DATA_FILE = "bot_data.json"
DROP_INTERVAL = 30  # 30 seconds for testing (change to 6*60 for production)

# ==============================
# 📊 DATA MANAGEMENT
# ==============================

class BotData:
    def __init__(self):
        self.senders: Set[int] = set()
        self.receivers: Set[int] = set()
        self.ip_queue: List[str] = []
        self.distributed_ips: Dict[int, List[str]] = {}  # user_id -> [ips]
        self.sending_active: bool = False
        self.user_intervals: Dict[int, int] = {}  # user_id -> interval_seconds
        self.active_timers: Dict[int, bool] = {}  # user_id -> is_timer_active
        self.load_data()
    
    def load_data(self):
        """Load data from JSON file"""
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r') as f:
                    data = json.load(f)
                    self.senders = set(data.get('senders', []))
                    self.receivers = set(data.get('receivers', []))
                    self.ip_queue = data.get('ip_queue', [])
                    self.distributed_ips = {int(k): v for k, v in data.get('distributed_ips', {}).items()}
                    self.sending_active = data.get('sending_active', False)
                    self.user_intervals = {int(k): v for k, v in data.get('user_intervals', {}).items()}
                    self.active_timers = {int(k): v for k, v in data.get('active_timers', {}).items()}
                logger.info(f"Data loaded: {len(self.senders)} senders, {len(self.receivers)} receivers, {len(self.ip_queue)} IPs")
        except Exception as e:
            logger.error(f"Error loading data: {e}")
    
    def save_data(self):
        """Save data to JSON file"""
        try:
            data = {
                'senders': list(self.senders),
                'receivers': list(self.receivers),
                'ip_queue': self.ip_queue,
                'distributed_ips': {str(k): v for k, v in self.distributed_ips.items()},
                'sending_active': self.sending_active,
                'user_intervals': {str(k): v for k, v in self.user_intervals.items()},
                'active_timers': {str(k): v for k, v in self.active_timers.items()},
                'last_updated': datetime.now().isoformat()
            }
            with open(DATA_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving data: {e}")
    
    def add_sender(self, user_id: int) -> bool:
        """Add user as sender"""
        if user_id not in self.senders:
            self.senders.add(user_id)
            # Remove from receivers if exists
            self.receivers.discard(user_id)
            self.save_data()
            return True
        return False
    
    def add_receiver(self, user_id: int) -> bool:
        """Add user as receiver"""
        if user_id not in self.receivers:
            self.receivers.add(user_id)
            # Remove from senders if exists
            self.senders.discard(user_id)
            # Initialize empty IP list
            if user_id not in self.distributed_ips:
                self.distributed_ips[user_id] = []
            self.save_data()
            return True
        return False
    
    def remove_user(self, user_id: int):
        """Remove user from both senders and receivers"""
        self.senders.discard(user_id)
        self.receivers.discard(user_id)
        if user_id in self.distributed_ips:
            del self.distributed_ips[user_id]
        if user_id in self.user_intervals:
            del self.user_intervals[user_id]
        if user_id in self.active_timers:
            del self.active_timers[user_id]
        self.save_data()
    
    def add_ips(self, ips: List[str]):
        """Add IPs to queue"""
        self.ip_queue.extend(ips)
        self.save_data()
    
    def get_next_ip_for_user(self, user_id: int) -> Optional[str]:
        """Get next available IP for specific user"""
        if not self.ip_queue:
            return None
        
        # Find an IP that hasn't been given to this user
        for i, ip in enumerate(self.ip_queue):
            if user_id not in self.distributed_ips:
                self.distributed_ips[user_id] = []
            
            if ip not in self.distributed_ips[user_id]:
                # Remove IP from queue and add to user's distributed list
                self.distributed_ips[user_id].append(ip)
                self.ip_queue.pop(i)
                self.save_data()
                return ip
        
        return None  # No new IPs available for this user
    
    def clear_queue(self):
        """Clear IP queue and distributed IPs"""
        self.ip_queue.clear()
        self.distributed_ips.clear()
        self.save_data()
    
    def set_user_interval(self, user_id: int, interval: int):
        """Set interval for user"""
        self.user_intervals[user_id] = interval
        self.save_data()
    
    def set_timer_active(self, user_id: int, active: bool):
        """Set timer active status for user"""
        self.active_timers[user_id] = active
        self.save_data()

# Global data instance
bot_data = BotData()
sending_task: Optional[asyncio.Task] = None
user_timers: Dict[int, asyncio.Task] = {}  # user_id -> timer_task

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==============================
# 🎛️ USER INTERFACE
# ==============================

def get_main_menu_keyboard():
    """Get main menu keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("📤 Become Sender", callback_data="become_sender"),
            InlineKeyboardButton("📥 Become Receiver", callback_data="become_receiver")
        ],
        [
            InlineKeyboardButton("📊 Status", callback_data="status"),
            InlineKeyboardButton("ℹ️ Help", callback_data="help")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_sender_menu_keyboard():
    """Get sender menu keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("📤 Push IPs", callback_data="push_ips"),
            InlineKeyboardButton("🚀 Start Sending", callback_data="start_sending")
        ],
        [
            InlineKeyboardButton("🛑 Stop Sending", callback_data="stop_sending"),
            InlineKeyboardButton("🗑️ Clear Queue", callback_data="clear_queue")
        ],
        [
            InlineKeyboardButton("📊 Status", callback_data="status"),
            InlineKeyboardButton("🔙 Back", callback_data="main_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_receiver_menu_keyboard(user_id: int = None):
    """Get receiver menu keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("📥 Get IP Now", callback_data="get_ip"),
            InlineKeyboardButton("📊 My Status", callback_data="my_status")
        ]
    ]
    
    # Add timer controls if user has active timer
    if user_id and user_id in bot_data.active_timers and bot_data.active_timers[user_id]:
        keyboard.append([
            InlineKeyboardButton("⏹️ Stop Timer", callback_data="stop_timer")
        ])
    
    keyboard.append([
        InlineKeyboardButton("🔙 Back", callback_data="main_menu")
    ])
    
    return InlineKeyboardMarkup(keyboard)

# ==============================
# 🤖 BOT HANDLERS
# ==============================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    if not update.message:
        return
    
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name if update.effective_user else "User"
    
    welcome_text = f"""
🤖 **Welcome {user_name}!**

**AutoDrop Bot - Dynamic System**

Choose your role:
• **Sender**: Push IPs and manage distribution
• **Receiver**: Get unique IPs on demand

**Features:**
✅ No IP conflicts - each user gets unique IPs
✅ Individual private messages
✅ Dynamic registration system
✅ Real-time status tracking
    """
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_menu_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    try:
        if data == "main_menu":
            await show_main_menu(query)
        
        elif data == "become_sender":
            await handle_become_sender(query)
        
        elif data == "become_receiver":
            await handle_become_receiver(query)
        
        elif data == "status":
            await show_status(query)
        
        elif data == "help":
            await show_help(query)
        
        elif data == "push_ips":
            await handle_push_request(query)
        
        elif data == "start_sending":
            await handle_start_sending(query)
        
        elif data == "stop_sending":
            await handle_stop_sending(query)
        
        elif data == "clear_queue":
            await handle_clear_queue(query)
        
        elif data == "get_ip":
            await handle_get_ip(query)
        
        elif data == "my_status":
            await show_my_status(query)
        
        elif data == "stop_timer":
            await handle_stop_timer(query)
    
    except Exception as e:
        logger.error(f"Error in button handler: {e}")
        await query.edit_message_text("❌ An error occurred. Please try again.")

async def show_main_menu(query):
    """Show main menu"""
    user_id = query.from_user.id
    
    # Check current role
    role = "None"
    if user_id in bot_data.senders:
        role = "Sender"
    elif user_id in bot_data.receivers:
        role = "Receiver"
    
    text = f"""
🤖 **AutoDrop Bot**

**Your Role:** {role}
**Total Senders:** {len(bot_data.senders)}
**Total Receivers:** {len(bot_data.receivers)}
**IPs in Queue:** {len(bot_data.ip_queue)}

Choose an option:
    """
    
    await query.edit_message_text(text, reply_markup=get_main_menu_keyboard())

async def handle_become_sender(query):
    """Handle become sender"""
    user_id = query.from_user.id
    
    if bot_data.add_sender(user_id):
        text = """
✅ **You are now a SENDER!**

**Sender Capabilities:**
• Push IPs to the system
• Start/stop distribution
• Manage IP queue
• View system status

Use the menu below to manage IPs:
        """
        await query.edit_message_text(text, reply_markup=get_sender_menu_keyboard())
    else:
        await query.edit_message_text("ℹ️ You are already a sender!", reply_markup=get_sender_menu_keyboard())

async def handle_become_receiver(query):
    """Handle become receiver"""
    user_id = query.from_user.id
    
    if bot_data.add_receiver(user_id):
        text = """
✅ **You are now a RECEIVER!**

**Receiver Capabilities:**
• Get unique IPs on demand
• No conflicts with other receivers
• Private IP delivery
• Track your received IPs

Use the menu below:
        """
        await query.edit_message_text(text, reply_markup=get_receiver_menu_keyboard(user_id))
    else:
        await query.edit_message_text("ℹ️ You are already a receiver!", reply_markup=get_receiver_menu_keyboard())

async def show_status(query):
    """Show system status"""
    total_distributed = sum(len(ips) for ips in bot_data.distributed_ips.values())
    
    text = f"""
📊 **System Status**

**Users:**
👥 Senders: {len(bot_data.senders)}
👥 Receivers: {len(bot_data.receivers)}

**IPs:**
📦 Queue: {len(bot_data.ip_queue)}
📤 Distributed: {total_distributed}

**Sending:**
🚚 Status: {'🟢 Active' if bot_data.sending_active else '🔴 Stopped'}

**Distribution per Receiver:**
    """
    
    for receiver_id in bot_data.receivers:
        count = len(bot_data.distributed_ips.get(receiver_id, []))
        text += f"\n• User {receiver_id}: {count} IPs"
    
    # Add back button based on user role
    user_id = query.from_user.id
    if user_id in bot_data.senders:
        keyboard = get_sender_menu_keyboard()
    elif user_id in bot_data.receivers:
        keyboard = get_receiver_menu_keyboard(user_id)
    else:
        keyboard = get_main_menu_keyboard()
    
    await query.edit_message_text(text, reply_markup=keyboard)

async def show_help(query):
    """Show help information"""
    text = """
📖 **Help & Instructions**

**For Senders:**
1. Click "Become Sender"
2. Use "Push IPs" to add IPs (send as message)
3. Click "Start Sending" to begin distribution
4. Receivers can then get IPs individually

**For Receivers:**
1. Click "Become Receiver"
2. Click "Get IP" to receive your unique IP
3. Each IP is given only once per receiver
4. No conflicts with other receivers

**Features:**
• Dynamic role switching
• Individual IP distribution
• Private message delivery
• Real-time status tracking

**Commands:**
/start - Main menu
/status - Quick status
/get <seconds> - Start automatic IP delivery
/stop_timer - Stop automatic delivery
/help - This help message

**Examples:**
/get 300 - Get IP every 5 minutes
/get 1800 - Get IP every 30 minutes
    """
    
    await query.edit_message_text(text, reply_markup=get_main_menu_keyboard())

async def handle_push_request(query):
    """Handle push IP request"""
    user_id = query.from_user.id
    
    if user_id not in bot_data.senders:
        await query.edit_message_text("❌ Only senders can push IPs!", reply_markup=get_main_menu_keyboard())
        return
    
    text = """
📤 **Push IPs to Queue**

Send me a message with IPs (one per line):

Example:
```
192.168.1.1
10.0.0.1
172.16.0.1
```

I'll add them to the queue automatically.
    """
    
    await query.edit_message_text(text, reply_markup=get_sender_menu_keyboard())

async def handle_start_sending(query):
    """Handle start sending"""
    global sending_task
    user_id = query.from_user.id
    
    if user_id not in bot_data.senders:
        await query.edit_message_text("❌ Only senders can start sending!", reply_markup=get_main_menu_keyboard())
        return
    
    if not bot_data.ip_queue:
        await query.edit_message_text("⚠️ No IPs in queue! Push some IPs first.", reply_markup=get_sender_menu_keyboard())
        return
    
    if bot_data.sending_active:
        await query.edit_message_text("⏳ Sending is already active!", reply_markup=get_sender_menu_keyboard())
        return
    
    bot_data.sending_active = True
    bot_data.save_data()
    
    text = f"""
🚀 **Sending Activated!**

**Status:**
📦 IPs in Queue: {len(bot_data.ip_queue)}
👥 Active Receivers: {len(bot_data.receivers)}

Receivers can now use "Get IP" to receive their unique IPs!
    """
    
    await query.edit_message_text(text, reply_markup=get_sender_menu_keyboard())

async def handle_stop_sending(query):
    """Handle stop sending"""
    user_id = query.from_user.id
    
    if user_id not in bot_data.senders:
        await query.edit_message_text("❌ Only senders can stop sending!", reply_markup=get_main_menu_keyboard())
        return
    
    bot_data.sending_active = False
    bot_data.save_data()
    
    await query.edit_message_text("🛑 Sending stopped!", reply_markup=get_sender_menu_keyboard())

async def handle_clear_queue(query):
    """Handle clear queue"""
    user_id = query.from_user.id
    
    if user_id not in bot_data.senders:
        await query.edit_message_text("❌ Only senders can clear queue!", reply_markup=get_main_menu_keyboard())
        return
    
    cleared_count = len(bot_data.ip_queue)
    distributed_count = sum(len(ips) for ips in bot_data.distributed_ips.values())
    
    bot_data.clear_queue()
    
    text = f"""
🗑️ **Queue Cleared!**

**Cleared:**
📦 Queue IPs: {cleared_count}
📤 Distributed IPs: {distributed_count}

All IP data has been reset.
    """
    
    await query.edit_message_text(text, reply_markup=get_sender_menu_keyboard())

async def handle_get_ip(query):
    """Handle get IP request"""
    user_id = query.from_user.id
    
    if user_id not in bot_data.receivers:
        await query.edit_message_text("❌ Only receivers can get IPs!", reply_markup=get_main_menu_keyboard())
        return
    
    if not bot_data.sending_active:
        await query.edit_message_text("⚠️ Sending is not active! Ask a sender to start sending.", reply_markup=get_receiver_menu_keyboard())
        return
    
    # Get next IP for this user
    ip = bot_data.get_next_ip_for_user(user_id)
    
    if ip:
        text = f"""
🌐 **Your IP:**

`{ip}`

**Status:**
✅ IP delivered successfully
📊 Your total IPs: {len(bot_data.distributed_ips.get(user_id, []))}
📦 Remaining in queue: {len(bot_data.ip_queue)}
        """
        
        # Also send IP in a separate message for easy copying
        await query.message.reply_text(f"🌐 **IP:** `{ip}`")
        
    else:
        text = """
⚠️ **No New IPs Available**

Either:
• Queue is empty
• You've received all available IPs

Ask a sender to add more IPs!
        """
    
    await query.edit_message_text(text, reply_markup=get_receiver_menu_keyboard())

async def show_my_status(query):
    """Show receiver's personal status"""
    user_id = query.from_user.id
    
    if user_id not in bot_data.receivers:
        await query.edit_message_text("❌ Only receivers can view this!", reply_markup=get_main_menu_keyboard())
        return
    
    my_ips = bot_data.distributed_ips.get(user_id, [])
    timer_active = bot_data.active_timers.get(user_id, False)
    interval = bot_data.user_intervals.get(user_id, 0)
    
    text = f"""
📊 **Your Status**

**Received IPs:** {len(my_ips)}
**Available in Queue:** {len(bot_data.ip_queue)}
**Sending Status:** {'🟢 Active' if bot_data.sending_active else '🔴 Stopped'}

**Timer Status:** {'🟢 Active' if timer_active else '🔴 Stopped'}
    """
    
    if timer_active and interval > 0:
        text += f"\n**Timer Interval:** {interval} seconds ({interval//60} minutes)"
    
    text += "\n\n**Your Recent IPs:**"
    
    # Show last 5 IPs
    recent_ips = my_ips[-5:] if my_ips else []
    for i, ip in enumerate(recent_ips, 1):
        text += f"\n{i}. `{ip}`"
    
    if len(my_ips) > 5:
        text += f"\n... and {len(my_ips) - 5} more"
    
    if not my_ips:
        text += "\nNo IPs received yet."
    
    await query.edit_message_text(text, reply_markup=get_receiver_menu_keyboard(user_id))

async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /get command with interval"""
    if not update.message:
        return
    
    user_id = update.effective_user.id
    
    # Check if user is receiver
    if user_id not in bot_data.receivers:
        await update.message.reply_text("❌ You need to be a receiver first! Use /start to register.")
        return
    
    # Check if sending is active
    if not bot_data.sending_active:
        await update.message.reply_text("⚠️ Sending is not active! Ask a sender to start sending.")
        return
    
    # Parse interval from command
    try:
        if context.args and len(context.args) > 0:
            interval = int(context.args[0])
            if interval < 30:  # Minimum 30 seconds
                await update.message.reply_text("⚠️ Minimum interval is 30 seconds!")
                return
            if interval > 86400:  # Maximum 24 hours
                await update.message.reply_text("⚠️ Maximum interval is 86400 seconds (24 hours)!")
                return
        else:
            await update.message.reply_text(
                "📖 **Usage:** `/get <interval_in_seconds>`\n\n"
                "**Examples:**\n"
                "• `/get 300` - Get IP every 5 minutes\n"
                "• `/get 600` - Get IP every 10 minutes\n"
                "• `/get 1800` - Get IP every 30 minutes\n\n"
                "**Range:** 30 seconds to 86400 seconds (24 hours)"
            )
            return
    except ValueError:
        await update.message.reply_text("❌ Invalid interval! Please use numbers only.")
        return
    
    # Stop existing timer if any
    if user_id in user_timers:
        await stop_user_timer(user_id)
    
    # Get first IP immediately
    first_ip = bot_data.get_next_ip_for_user(user_id)
    
    if not first_ip:
        await update.message.reply_text("⚠️ No IPs available in queue!")
        return
    
    # Send first IP
    await update.message.reply_text(
        f"🌐 **First IP (Immediate):**\n\n`{first_ip}`\n\n"
        f"⏰ **Timer Started!**\n"
        f"📅 Interval: {interval} seconds ({interval//60} minutes)\n"
        f"🔄 Next IP in: {interval} seconds\n\n"
        f"Use `/stop_timer` to stop automatic delivery."
    )
    
    # Save user interval and start timer
    bot_data.set_user_interval(user_id, interval)
    bot_data.set_timer_active(user_id, True)
    
    # Start background timer
    user_timers[user_id] = asyncio.create_task(
        start_user_timer(user_id, interval, context.application)
    )
    
    logger.info(f"User {user_id} started timer with {interval}s interval")

async def stop_timer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stop_timer command"""
    if not update.message:
        return
    
    user_id = update.effective_user.id
    
    if user_id not in bot_data.active_timers or not bot_data.active_timers[user_id]:
        await update.message.reply_text("ℹ️ You don't have an active timer.")
        return
    
    await stop_user_timer(user_id)
    
    await update.message.reply_text("⏹️ **Timer Stopped!**\n\nAutomatic IP delivery has been cancelled.")
    logger.info(f"User {user_id} stopped their timer")

async def handle_stop_timer(query):
    """Handle stop timer button"""
    user_id = query.from_user.id
    
    if user_id not in bot_data.active_timers or not bot_data.active_timers[user_id]:
        await query.edit_message_text("ℹ️ You don't have an active timer.", reply_markup=get_receiver_menu_keyboard(user_id))
        return
    
    await stop_user_timer(user_id)
    
    await query.edit_message_text("⏹️ **Timer Stopped!**\n\nAutomatic IP delivery has been cancelled.", reply_markup=get_receiver_menu_keyboard(user_id))

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (for IP pushing)"""
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    
    # Check if user is sender
    if user_id not in bot_data.senders:
        await update.message.reply_text("ℹ️ Use /start to access the bot menu.")
        return
    
    # Extract IPs from message
    text = update.message.text.strip()
    lines = text.split('\n')
    
    new_ips = []
    for line in lines:
        ip = line.strip()
        # Basic IP validation
        if ip and '.' in ip and len(ip.split('.')) == 4:
            try:
                parts = ip.split('.')
                if all(0 <= int(part) <= 255 for part in parts):
                    new_ips.append(ip)
            except ValueError:
                continue
    
    if new_ips:
        bot_data.add_ips(new_ips)
        
        await update.message.reply_text(
            f"✅ **Added {len(new_ips)} IPs to queue!**\n\n"
            f"📦 Total in queue: {len(bot_data.ip_queue)}\n"
            f"👥 Active receivers: {len(bot_data.receivers)}",
            reply_markup=get_sender_menu_keyboard()
        )
        
        logger.info(f"Sender {user_id} added {len(new_ips)} IPs")
    else:
        await update.message.reply_text(
            "⚠️ No valid IPs found in your message.\n\n"
            "Please send IPs in format:\n"
            "192.168.1.1\n"
            "10.0.0.1\n"
            "172.16.0.1",
            reply_markup=get_sender_menu_keyboard()
        )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick status command"""
    if not update.message:
        return
    
    total_distributed = sum(len(ips) for ips in bot_data.distributed_ips.values())
    
    text = f"""
📊 **Quick Status**

👥 Senders: {len(bot_data.senders)} | Receivers: {len(bot_data.receivers)}
📦 Queue: {len(bot_data.ip_queue)} | Distributed: {total_distributed}
🚚 Sending: {'🟢 Active' if bot_data.sending_active else '🔴 Stopped'}

Use /start for full menu.
    """
    
    await update.message.reply_text(text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    if not update.message:
        return
    
    await update.message.reply_text(
        "📖 Use /start to access the main menu with all features!",
        reply_markup=get_main_menu_keyboard()
    )

# ==============================
# ⏰ TIMER FUNCTIONS
# ==============================

async def start_user_timer(user_id: int, interval: int, app: Application):
    """Start automatic IP delivery timer for user"""
    try:
        logger.info(f"Starting timer for user {user_id} with {interval}s interval")
        
        while bot_data.active_timers.get(user_id, False):
            await asyncio.sleep(interval)
            
            # Check if timer is still active and user is still receiver
            if not bot_data.active_timers.get(user_id, False) or user_id not in bot_data.receivers:
                break
            
            # Check if sending is active
            if not bot_data.sending_active:
                continue
            
            # Get next IP for user
            ip = bot_data.get_next_ip_for_user(user_id)
            
            if ip:
                try:
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=f"🌐 **Auto IP Delivery**\n\n`{ip}`\n\n⏰ Next IP in {interval//60} minutes"
                    )
                    logger.info(f"Auto-delivered IP {ip} to user {user_id}")
                except Exception as e:
                    logger.error(f"Failed to auto-deliver IP to {user_id}: {e}")
            else:
                # No more IPs available
                try:
                    await app.bot.send_message(
                        chat_id=user_id,
                        text="⚠️ **Timer Active but No IPs Available**\n\nWaiting for more IPs to be added..."
                    )
                except Exception as e:
                    logger.error(f"Failed to send no-IP message to {user_id}: {e}")
        
        # Timer stopped
        logger.info(f"Timer stopped for user {user_id}")
        
    except asyncio.CancelledError:
        logger.info(f"Timer cancelled for user {user_id}")
        raise
    except Exception as e:
        logger.error(f"Timer error for user {user_id}: {e}")

async def stop_user_timer(user_id: int):
    """Stop timer for user"""
    if user_id in user_timers:
        user_timers[user_id].cancel()
        try:
            await user_timers[user_id]
        except asyncio.CancelledError:
            pass
        del user_timers[user_id]
    
    bot_data.set_timer_active(user_id, False)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error("Exception while handling update:", exc_info=context.error)

def main():
    """Main function"""
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Please set BOT_TOKEN in the configuration")
        return
    
    logger.info("Starting Dynamic AutoDrop Bot...")
    logger.info(f"Loaded: {len(bot_data.senders)} senders, {len(bot_data.receivers)} receivers")
    
    # Create application
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("get", get_command))
    app.add_handler(CommandHandler("stop_timer", stop_timer_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    # Add error handler
    app.add_error_handler(error_handler)
    
    try:
        logger.info("🤖 Dynamic AutoDrop Bot is running...")
        app.run_polling(drop_pending_updates=True)
    except Conflict:
        logger.error("Another bot instance is running!")
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")

if __name__ == "__main__":
    main()
