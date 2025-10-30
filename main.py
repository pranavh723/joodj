#!/usr/bin/env python3
"""
🤖 Complete AutoDrop Telegram Bot - All-in-One Version
=======================================================

Features:
- Dynamic sender/receiver registration (no hardcoded IDs)
- Individual IP distribution (no conflicts between users)
- Timer-based automatic IP delivery (/get interval)
- User-friendly interface with buttons
- Data persistence (survives restarts)
- Real-time status tracking

Usage:
1. Get bot token from @BotFather
2. Set BOT_TOKEN below
3. Run: python complete_autodrop_bot.py

Commands:
- /start - Main menu
- /get <seconds> - Start automatic IP delivery
- /stop_timer - Stop automatic delivery
- /status - Quick status
- /help - Help information

Author: Kiro AI Assistant
Version: 2.0
"""

import asyncio
import json
import logging
import os
import signal
import sys
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

# Set your bot token here (get from @BotFather)
BOT_TOKEN = "8222403305:AAHJ9ewwYYNa3lWFm3fZhgBplCP65e6g054"

# Data file for persistence
DATA_FILE = "bot_data.json"

# Timer limits
MIN_INTERVAL = 30      # Minimum 30 seconds
MAX_INTERVAL = 86400   # Maximum 24 hours

# ==============================
# 📊 DATA MANAGEMENT CLASS
# ==============================

class BotData:
    """Manages all bot data with persistence"""
    
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
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
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
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
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

# ==============================
# 🌐 GLOBAL VARIABLES
# ==============================

# Global data instance
bot_data = BotData()
user_timers: Dict[int, asyncio.Task] = {}  # user_id -> timer_task

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ==============================
# 🎛️ USER INTERFACE KEYBOARDS
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
                        text=ip
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
    try:
        # Mark timer as inactive - it will stop naturally
        bot_data.set_timer_active(user_id, False)
        
        # Remove from active timers dict
        if user_id in user_timers:
            del user_timers[user_id]
        
        logger.info(f"Timer stopped for user {user_id}")
    except Exception as e:
        logger.error(f"Error stopping timer for user {user_id}: {e}")

# ==============================
# 🤖 COMMAND HANDLERS
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

**Key Features:**
✅ No IP conflicts - each user gets unique IPs
✅ Individual private messages
✅ Dynamic registration system
✅ Timer-based automatic delivery
✅ Real-time status tracking
✅ Data persistence across restarts

**Quick Commands:**
• `/get 300` - Get IP every 5 minutes
• `/get 1800` - Get IP every 30 minutes
• `/stop_timer` - Stop automatic delivery
    """
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_menu_keyboard()
    )

async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /get command with interval"""
    if not update.message:
        return
    
    user_id = update.effective_user.id
    
    # Check if user is receiver
    if user_id not in bot_data.receivers:
        await update.message.reply_text(
            "❌ You need to be a receiver first!\n\n"
            "Use /start and click 'Become Receiver' to register."
        )
        return
    
    # Check if sending is active
    if not bot_data.sending_active:
        await update.message.reply_text(
            "⚠️ Sending is not active!\n\n"
            "Ask a sender to start the distribution system."
        )
        return
    
    # Parse interval from command
    try:
        if context.args and len(context.args) > 0:
            interval = int(context.args[0])
            if interval < MIN_INTERVAL:
                await update.message.reply_text(f"⚠️ Minimum interval is {MIN_INTERVAL} seconds!")
                return
            if interval > MAX_INTERVAL:
                await update.message.reply_text(f"⚠️ Maximum interval is {MAX_INTERVAL} seconds (24 hours)!")
                return
        else:
            await update.message.reply_text(
                "📖 **Usage:** `/get <interval_in_seconds>`\n\n"
                "**Examples:**\n"
                "• `/get 300` - Get IP every 5 minutes\n"
                "• `/get 600` - Get IP every 10 minutes\n"
                "• `/get 1800` - Get IP every 30 minutes\n"
                "• `/get 3600` - Get IP every 1 hour\n\n"
                f"**Range:** {MIN_INTERVAL} seconds to {MAX_INTERVAL} seconds (24 hours)"
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
    
    # Send first IP - clean format
    await update.message.reply_text(first_ip)
    
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
    
    await update.message.reply_text(
        "⏹️ **Timer Stopped Successfully!**\n\n"
        "Automatic IP delivery has been cancelled.\n"
        "Use `/get <interval>` to start a new timer."
    )
    logger.info(f"User {user_id} stopped their timer")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick status command"""
    if not update.message:
        return
    
    total_distributed = sum(len(ips) for ips in bot_data.distributed_ips.values())
    active_timers = sum(1 for active in bot_data.active_timers.values() if active)
    
    text = f"""
📊 **Quick Status**

👥 **Users:**
• Senders: {len(bot_data.senders)}
• Receivers: {len(bot_data.receivers)}
• Active Timers: {active_timers}

📦 **IPs:**
• In Queue: {len(bot_data.ip_queue)}
• Distributed: {total_distributed}

🚚 **System:**
• Sending: {'🟢 Active' if bot_data.sending_active else '🔴 Stopped'}

Use /start for full menu and detailed controls.
    """
    
    await update.message.reply_text(text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    if not update.message:
        return
    
    help_text = """
📖 **AutoDrop Bot Help**

**Main Commands:**
• `/start` - Access main menu
• `/get <seconds>` - Start automatic IP delivery
• `/stop_timer` - Stop automatic delivery
• `/status` - Quick system status
• `/help` - This help message

**How to Use:**

**For Senders:**
1. Use /start → "Become Sender"
2. Send IPs as text messages (one per line)
3. Click "Start Sending" to activate system
4. Manage queue and monitor distribution

**For Receivers:**
1. Use /start → "Become Receiver"
2. Use `/get 300` for IP every 5 minutes
3. Or click "Get IP Now" for immediate IP
4. Each user gets unique IPs (no conflicts)

**Timer Examples:**
• `/get 300` - Every 5 minutes
• `/get 600` - Every 10 minutes
• `/get 1800` - Every 30 minutes
• `/get 3600` - Every 1 hour

**Features:**
✅ Dynamic user registration
✅ Individual IP distribution
✅ Timer-based automation
✅ Data persistence
✅ Real-time status tracking
    """
    
    await update.message.reply_text(
        help_text,
        reply_markup=get_main_menu_keyboard()
    )

# ==============================
# 🎛️ BUTTON HANDLERS
# ==============================

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
🤖 **AutoDrop Bot - Main Menu**

**Your Current Role:** {role}

**System Overview:**
👥 Total Senders: {len(bot_data.senders)}
👥 Total Receivers: {len(bot_data.receivers)}
📦 IPs in Queue: {len(bot_data.ip_queue)}
🚚 System Status: {'🟢 Active' if bot_data.sending_active else '🔴 Stopped'}

Choose an option below:
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
• Clear all data
• View detailed system status

**How to Add IPs:**
Just send me a text message with IPs (one per line):
```
192.168.1.1
10.0.0.1
172.16.0.1
```

Use the menu below to manage the system:
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
• Set up automatic IP delivery timers
• No conflicts with other receivers
• Private IP delivery
• Track your received IPs

**Quick Start:**
• Click "Get IP Now" for immediate IP
• Use `/get 300` for IP every 5 minutes
• Use `/get 1800` for IP every 30 minutes

Use the menu below:
        """
        await query.edit_message_text(text, reply_markup=get_receiver_menu_keyboard(user_id))
    else:
        await query.edit_message_text("ℹ️ You are already a receiver!", reply_markup=get_receiver_menu_keyboard(user_id))

async def show_status(query):
    """Show system status"""
    total_distributed = sum(len(ips) for ips in bot_data.distributed_ips.values())
    active_timers = sum(1 for active in bot_data.active_timers.values() if active)
    
    text = f"""
📊 **Detailed System Status**

**Users:**
👥 Senders: {len(bot_data.senders)}
👥 Receivers: {len(bot_data.receivers)}
⏰ Active Timers: {active_timers}

**IPs:**
📦 In Queue: {len(bot_data.ip_queue)}
📤 Total Distributed: {total_distributed}

**System:**
🚚 Sending Status: {'🟢 Active' if bot_data.sending_active else '🔴 Stopped'}

**Distribution per Receiver:**
    """
    
    if bot_data.receivers:
        for receiver_id in list(bot_data.receivers)[:10]:  # Show max 10 receivers
            count = len(bot_data.distributed_ips.get(receiver_id, []))
            timer_status = "⏰" if bot_data.active_timers.get(receiver_id, False) else "⏹️"
            text += f"\n• User {receiver_id}: {count} IPs {timer_status}"
        
        if len(bot_data.receivers) > 10:
            text += f"\n... and {len(bot_data.receivers) - 10} more receivers"
    else:
        text += "\nNo receivers registered yet."
    
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
2. Send IPs as text messages (one per line)
3. Click "Start Sending" to activate system
4. Receivers can then get IPs individually

**For Receivers:**
1. Click "Become Receiver"
2. Use `/get <seconds>` for automatic delivery
3. Or click "Get IP Now" for immediate IP
4. Each IP is unique per receiver (no conflicts)

**Timer Commands:**
• `/get 300` - IP every 5 minutes
• `/get 600` - IP every 10 minutes
• `/get 1800` - IP every 30 minutes
• `/stop_timer` - Stop automatic delivery

**Features:**
• Dynamic role switching
• Individual IP distribution
• Timer-based automation
• Private message delivery
• Real-time status tracking
• Data persistence across restarts

**Commands:**
/start - Main menu
/get <seconds> - Start automatic delivery
/stop_timer - Stop automatic delivery
/status - Quick status
/help - This help message
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

**Example:**
```
192.168.1.1
10.0.0.1
172.16.0.1
203.0.113.1
198.51.100.1
```

**Tips:**
• One IP per line
• IPv4 format only
• No spaces or extra characters
• I'll validate and add them automatically

Just type your IPs and send the message!
    """
    
    await query.edit_message_text(text, reply_markup=get_sender_menu_keyboard())

async def handle_start_sending(query):
    """Handle start sending"""
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
🚀 **Sending System Activated!**

**Current Status:**
📦 IPs in Queue: {len(bot_data.ip_queue)}
👥 Active Receivers: {len(bot_data.receivers)}
⏰ Active Timers: {sum(1 for active in bot_data.active_timers.values() if active)}

**What's Next:**
• Receivers can now get IPs using "Get IP Now"
• Timer users will receive IPs automatically
• Each receiver gets unique IPs (no conflicts)

System is now ready for IP distribution!
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
    
    text = """
🛑 **Sending System Stopped!**

**What This Means:**
• No new IPs will be distributed
• Active timers will pause (but not stop)
• Receivers will get "not active" message
• Queue and user data remain intact

**To Resume:**
Click "Start Sending" when ready to continue distribution.
    """
    
    await query.edit_message_text(text, reply_markup=get_sender_menu_keyboard())

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
🗑️ **Queue Cleared Successfully!**

**Cleared Data:**
📦 Queue IPs: {cleared_count}
📤 Distributed IPs: {distributed_count}

**What Happened:**
• All IPs removed from queue
• All user IP history cleared
• Timers remain active (will wait for new IPs)
• User registrations preserved

**Next Steps:**
Push new IPs to restart distribution.
    """
    
    await query.edit_message_text(text, reply_markup=get_sender_menu_keyboard())

async def handle_get_ip(query):
    """Handle get IP request"""
    user_id = query.from_user.id
    
    if user_id not in bot_data.receivers:
        await query.edit_message_text("❌ Only receivers can get IPs!", reply_markup=get_main_menu_keyboard())
        return
    
    if not bot_data.sending_active:
        await query.edit_message_text(
            "⚠️ **Sending System Not Active**\n\n"
            "The distribution system is currently stopped.\n"
            "Ask a sender to activate it first.",
            reply_markup=get_receiver_menu_keyboard(user_id)
        )
        return
    
    # Get next IP for this user
    ip = bot_data.get_next_ip_for_user(user_id)
    
    if ip:
        # Send clean IP
        await query.message.reply_text(ip)
        
        text = f"""
✅ **IP Delivered Successfully**

📊 Your total IPs: {len(bot_data.distributed_ips.get(user_id, []))}
� Remraining in queue: {len(bot_data.ip_queue)}

� Use `/get 300` for automatic delivery every 5 minutes!
        """
        
    else:
        text = """
⚠️ **No New IPs Available**

**Possible Reasons:**
• Queue is empty
• You've received all available IPs

**Solutions:**
• Ask a sender to add more IPs
• Wait for new IPs to be added
• Check back later

Your timer (if active) will resume when new IPs are available.
        """
    
    await query.edit_message_text(text, reply_markup=get_receiver_menu_keyboard(user_id))

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
📊 **Your Personal Status**

**IP Statistics:**
📥 Received IPs: {len(my_ips)}
📦 Available in Queue: {len(bot_data.ip_queue)}
🚚 System Status: {'🟢 Active' if bot_data.sending_active else '🔴 Stopped'}

**Timer Status:**
⏰ Timer: {'🟢 Active' if timer_active else '🔴 Stopped'}
    """
    
    if timer_active and interval > 0:
        text += f"📅 Interval: {interval} seconds ({interval//60} minutes)"
    
    text += "\n\n**Your Recent IPs:**"
    
    # Show last 5 IPs
    recent_ips = my_ips[-5:] if my_ips else []
    if recent_ips:
        for i, ip in enumerate(recent_ips, 1):
            text += f"\n{i}. `{ip}`"
        
        if len(my_ips) > 5:
            text += f"\n... and {len(my_ips) - 5} more IPs"
    else:
        text += "\nNo IPs received yet."
    
    text += f"\n\n**Commands:**\n• `/get 300` - Start 5min timer\n• `/stop_timer` - Stop timer"
    
    await query.edit_message_text(text, reply_markup=get_receiver_menu_keyboard(user_id))

async def handle_stop_timer(query):
    """Handle stop timer button"""
    user_id = query.from_user.id
    
    if user_id not in bot_data.active_timers or not bot_data.active_timers[user_id]:
        await query.edit_message_text(
            "ℹ️ You don't have an active timer.",
            reply_markup=get_receiver_menu_keyboard(user_id)
        )
        return
    
    await stop_user_timer(user_id)
    
    await query.edit_message_text(
        "⏹️ **Timer Stopped Successfully!**\n\n"
        "Automatic IP delivery has been cancelled.\n"
        "Use `/get <interval>` to start a new timer.",
        reply_markup=get_receiver_menu_keyboard(user_id)
    )

# ==============================
# 📝 MESSAGE HANDLER
# ==============================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (for IP pushing)"""
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    
    # Check if user is sender
    if user_id not in bot_data.senders:
        await update.message.reply_text(
            "ℹ️ **Welcome!**\n\n"
            "Use /start to access the bot menu and choose your role.\n\n"
            "• **Sender**: Manage IP distribution\n"
            "• **Receiver**: Get unique IPs"
        )
        return
    
    # Extract IPs from message
    text = update.message.text.strip()
    lines = text.split('\n')
    
    new_ips = []
    invalid_lines = []
    
    for line_num, line in enumerate(lines, 1):
        ip = line.strip()
        # Basic IP validation
        if ip and '.' in ip and len(ip.split('.')) == 4:
            try:
                parts = ip.split('.')
                if all(0 <= int(part) <= 255 for part in parts):
                    new_ips.append(ip)
                else:
                    invalid_lines.append(f"Line {line_num}: {ip}")
            except ValueError:
                invalid_lines.append(f"Line {line_num}: {ip}")
        elif ip:  # Non-empty but invalid
            invalid_lines.append(f"Line {line_num}: {ip}")
    
    if new_ips:
        bot_data.add_ips(new_ips)
        
        response = f"✅ **Successfully Added {len(new_ips)} IPs!**\n\n"
        response += f"📦 Total in queue: {len(bot_data.ip_queue)}\n"
        response += f"👥 Active receivers: {len(bot_data.receivers)}\n"
        response += f"🚚 System status: {'🟢 Active' if bot_data.sending_active else '🔴 Stopped'}"
        
        if invalid_lines and len(invalid_lines) <= 5:
            response += f"\n\n⚠️ **Invalid IPs (skipped):**\n"
            for invalid in invalid_lines:
                response += f"• {invalid}\n"
        elif invalid_lines:
            response += f"\n\n⚠️ **{len(invalid_lines)} invalid IPs were skipped**"
        
        await update.message.reply_text(
            response,
            reply_markup=get_sender_menu_keyboard()
        )
        
        logger.info(f"Sender {user_id} added {len(new_ips)} IPs ({len(invalid_lines)} invalid)")
    else:
        await update.message.reply_text(
            "⚠️ **No Valid IPs Found**\n\n"
            "Please send IPs in correct format:\n\n"
            "**Example:**\n"
            "```\n"
            "192.168.1.1\n"
            "10.0.0.1\n"
            "172.16.0.1\n"
            "```\n\n"
            "**Requirements:**\n"
            "• One IP per line\n"
            "• IPv4 format (xxx.xxx.xxx.xxx)\n"
            "• Numbers 0-255 only",
            reply_markup=get_sender_menu_keyboard()
        )

# ==============================
# 🚨 ERROR HANDLER
# ==============================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error("Exception while handling update:", exc_info=context.error)
    
    # Try to notify user about error
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ **An error occurred**\n\nPlease try again or use /start to return to main menu."
            )
        except Exception:
            pass  # Don't fail on error notification failure

# ==============================
# 🚀 MAIN FUNCTION
# ==============================

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    print(f"\n🛑 Received signal {signum}, shutting down gracefully...")
    
    # Just mark timers as inactive, let them stop naturally
    try:
        for user_id in list(user_timers.keys()):
            bot_data.set_timer_active(user_id, False)
        logger.info("Marked all timers for shutdown")
    except Exception as e:
        logger.error(f"Error in signal handler: {e}")
    
    sys.exit(0)

def main():
    """Main function to start the bot"""
    
    # Setup signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Validate configuration
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Error: Please set your BOT_TOKEN in the configuration section")
        print("   Get your token from @BotFather on Telegram")
        return
    
    print("🤖 Starting AutoDrop Bot...")
    print(f"📊 Loaded: {len(bot_data.senders)} senders, {len(bot_data.receivers)} receivers")
    print(f"📦 Queue: {len(bot_data.ip_queue)} IPs")
    print(f"🚚 System: {'Active' if bot_data.sending_active else 'Stopped'}")
    
    # Create application
    try:
        app = ApplicationBuilder().token(BOT_TOKEN).build()
    except Exception as e:
        print(f"❌ Error creating bot application: {e}")
        return
    
    # Add command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("get", get_command))
    app.add_handler(CommandHandler("stop_timer", stop_timer_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("help", help_command))
    
    # Add button and message handlers
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    # Add error handler
    app.add_error_handler(error_handler)
    
    # Start the bot
    try:
        print("🚀 Bot is running... Press Ctrl+C to stop")
        logger.info("AutoDrop Bot started successfully")
        app.run_polling(drop_pending_updates=True)
    except Conflict:
        print("❌ Error: Another bot instance is running with this token!")
        logger.error("Bot conflict - another instance running")
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
        logger.info("Bot stopped by user")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        logger.error(f"Unexpected bot error: {e}")
    
    # Cleanup after bot stops (while event loop is still active)
    print("🧹 Cleaning up...")
    cleanup_timers()
    print("✅ Cleanup completed")

def cleanup_timers():
    """Clean up all active timers"""
    try:
        # Mark all timers as inactive in data
        for user_id in list(user_timers.keys()):
            bot_data.set_timer_active(user_id, False)
        
        # Clear the timers dict (don't cancel as they'll stop naturally)
        user_timers.clear()
        logger.info("All timers cleaned up successfully")
    except Exception as e:
        logger.error(f"Error during timer cleanup: {e}")

# ==============================
# 🎯 ENTRY POINT
# ==============================

if __name__ == "__main__":
    main()
