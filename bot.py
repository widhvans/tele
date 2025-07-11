# bot.py
# Main file for the Manager Bot (v1.6 - Forced Interaction to Fix Entity Error)

import asyncio
import logging
import re
from telethon import TelegramClient, events, Button, functions
from telethon.sessions import StringSession
from telethon.errors import UserAlreadyParticipantError, ChatAdminRequiredError, UserNotParticipantError
from telethon.tl.functions.channels import EditAdminRequest, LeaveChannelRequest
from telethon.tl.types import ChatAdminRights

import config
import database as db

# --- Logging Setup ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
LOGGER = logging.getLogger(__name__)

# --- Bot Initialization ---
bot = TelegramClient('manager_bot_session', config.API_ID, config.API_HASH).start(bot_token=config.BOT_TOKEN)
user_client = None  # Userbot client will be initialized after login

# --- Helper Functions ---
async def initialize_user_client():
    """Initialize the userbot client from stored session."""
    global user_client
    owner = db.get_user(config.OWNER_ID)
    if owner and owner.get('session_string'):
        session = StringSession(owner['session_string'])
        user_client = TelegramClient(session, config.API_ID, config.API_HASH,
                                       device_model=config.DEVICE_MODEL,
                                       system_version=config.SYSTEM_VERSION,
                                       app_version=config.APP_VERSION,
                                       lang_code=config.LANG_CODE,
                                       system_lang_code=config.SYSTEM_LANG_CODE)
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
            "2. Make me an administrator with full rights.\n"
            "I will help the group owner manage other bots.",
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
    owner = db.get_user(config.OWNER_ID)
    if owner and owner.get('state') == 'awaiting_phone':
        if re.match(r'\+?\d[\d\s-]{8,}\d', text):
            await process_login_phone(event, text.strip())
        else:
            await event.respond("⚠️ Invalid phone number format. Please try again.")
        return

    if text == "🔒 Login":
        db.update_user_state(config.OWNER_ID, 'awaiting_phone')
        await event.respond(
            "Please send your phone number (with country code, e.g., `+919876543210`) or use the button below.",
            buttons=Button.request_phone("📱 Share Contact", resize=True)
        )
    elif text == "🌐 Connected Chats":
        if not user_client: return await event.respond("⚠️ Please login first.")
        chats = db.get_connected_chats()
        if not chats: return await event.respond("📭 No connected chats found.")
        response = "**🌐 Connected Chats:**\n\n" + "\n".join([f"• **{c['title']}** (`{c['chat_id']}`)" for c in chats])
        await event.respond(response)
    elif text == "🤖 Add New Bot":
        if not user_client: return await event.respond("⚠️ Please login first.")
        async with bot.conversation(config.OWNER_ID, timeout=60) as conv:
            await conv.send_message("Please send the **username** of the **new bot** you want to add as admin (e.g., `@NewBot`).")
            response = await conv.get_response()
            if response.text and response.text.startswith('@'):
                await add_bot_process(event, response.text.strip())
            else:
                await conv.send_message("⚠️ Invalid format. Please send a valid username starting with `@`.")
    elif text == "📊 Stats":
        total_users, connected_chats = len(db.get_all_users()), len(db.get_connected_chats())
        await event.respond(f"**📊 Bot Stats:**\n\n👤 **Total Users:** {total_users}\n🌐 **Connected Chats:** {connected_chats}")
    elif text == "📣 Broadcast":
        # Broadcast logic here
        pass

# --- Login Process ---
@bot.on(events.NewMessage(func=lambda e: e.is_private and e.contact and e.sender_id == config.OWNER_ID))
async def phone_handler_button(event):
    await process_login_phone(event, event.message.contact.phone_number)

async def process_login_phone(event, phone_number):
    db.update_user_state(config.OWNER_ID, None)
    temp_client = TelegramClient(StringSession(), config.API_ID, config.API_HASH)
    await temp_client.connect()
    try:
        async with bot.conversation(config.OWNER_ID, timeout=300) as conv:
            code_request = await temp_client.send_code_request(phone_number)
            await conv.send_message("Please send the OTP you received from Telegram.")
            otp_code = await conv.get_response()
            try:
                await temp_client.sign_in(phone_number, code=otp_code.text, phone_code_hash=code_request.phone_code_hash)
            except Exception as e:
                if "password" in str(e).lower():
                    await conv.send_message("Your account has 2FA enabled. Please send your password.")
                    password = await conv.get_response()
                    await temp_client.sign_in(password=password.text)
                else: raise e
        session_string = temp_client.session.save()
        db.update_session(config.OWNER_ID, session_string)
        await event.respond("✅ **Login Successful!** Userbot is now active.")
        await initialize_user_client()
    except Exception as e:
        await event.respond(f"❌ Login failed: {e}")
    finally:
        if temp_client.is_connected(): await temp_client.disconnect()

# --- Core "Add Bot" Logic with New Workflow ---
async def add_bot_process(event, new_bot_username):
    if not user_client: return await event.respond("⚠️ Userbot is not active. Please login first.")
    
    status_msg = await event.respond(f"🔄 Starting process to add `{new_bot_username}`...")
    
    # ** THE FIX: Force interaction with the new bot to get its entity **
    try:
        LOGGER.info(f"Attempting to force interaction with {new_bot_username}...")
        await user_client.send_message(new_bot_username, '/start')
        await asyncio.sleep(2)  # Wait for the action to complete
        new_bot_entity = await user_client.get_entity(new_bot_username)
        LOGGER.info(f"Successfully resolved entity for {new_bot_username}.")
    except Exception as e:
        return await status_msg.edit(f"❌ **Error:** Could not find or interact with the bot `{new_bot_username}`. Please ensure the username is correct and the bot is not deactivated.\n\n`{e}`")

    chats = db.get_connected_chats()
    total_chats = len(chats)
    if total_chats == 0: return await status_msg.edit("No connected chats to process.")
    
    admin_done, admin_failed = 0, 0
    admin_rights = ChatAdminRights(change_info=True, post_messages=True, edit_messages=True, delete_messages=True, ban_users=True, invite_users=True, pin_messages=True, add_admins=True, manage_call=True)

    await status_msg.edit(f"✅ Bot recognized. Starting to process {total_chats} chats...")
    
    for i, chat_info in enumerate(chats):
        chat_id = chat_info['chat_id']
        chat_title = chat_info['title']
        
        await status_msg.edit(f"**🔄 Progress: {i+1}/{total_chats}**\nProcessing: `{chat_title}`")
        
        try:
            channel_entity = await user_client.get_entity(chat_id)
            
            # 1. Userbot joins the channel
            try:
                await user_client(functions.channels.JoinChannelRequest(channel=channel_entity))
                LOGGER.info(f"Userbot joined {chat_title}")
                await asyncio.sleep(3)
            except UserAlreadyParticipantError:
                LOGGER.info(f"Userbot is already in {chat_title}")
            
            # 2. Invite the new bot
            try:
                await user_client(functions.channels.InviteToChannelRequest(channel=channel_entity, users=[new_bot_entity]))
                LOGGER.info(f"Invited {new_bot_username} to {chat_title}")
                await asyncio.sleep(3)
            except (UserAlreadyParticipantError, UserNotParticipantError):
                 LOGGER.info(f"{new_bot_username} is already in {chat_title}")

            # 3. Promote the new bot
            await user_client(EditAdminRequest(channel=channel_entity, user_id=new_bot_entity, admin_rights=admin_rights, rank='bot'))
            LOGGER.info(f"Promoted {new_bot_username} in {chat_title}")
            
            # 4. Userbot leaves the channel
            await user_client(LeaveChannelRequest(channel=channel_entity))
            LOGGER.info(f"Userbot left {chat_title}")
            
            admin_done += 1

        except ChatAdminRequiredError:
            LOGGER.error(f"Failed in {chat_title}: Userbot lacks admin rights to perform actions.")
            admin_failed += 1
        except Exception as e:
            LOGGER.error(f"An unexpected error occurred in {chat_title}: {e}")
            admin_failed += 1
        
        await asyncio.sleep(5) 

    await status_msg.edit(
        f"✅ **Process Complete!**\n\n"
        f"**Total Chats:** {total_chats}\n"
        f"✅ **Successfully Processed:** {admin_done}\n"
        f"❌ **Failed:** {admin_failed}"
    )

# --- Main Execution ---
async def main():
    LOGGER.info("Bot starting...")
    if "state" not in (db.users_col.find_one() or {}):
        db.users_col.update_many({}, {"$set": {"state": None}})
        LOGGER.info("Added 'state' field to user documents.")
    await initialize_user_client()
    await bot.run_until_disconnected()

if __name__ == "__main__":
    def update_user_state(user_id, state):
        db.users_col.update_one({"user_id": user_id}, {"$set": {"state": state}})
    db.update_user_state = update_user_state
    bot.loop.run_until_complete(main())
