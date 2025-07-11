# bot.py
# Main file for the Manager Bot (v1.3 - Entity Error Fix & Hindi Language)

import asyncio
import logging
import re
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import UserNotParticipantError, ChatAdminRequiredError
from telethon.tl.functions.channels import EditAdminRequest
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
        # Owner's special interface
        is_logged_in = user_client and user_client.is_connected()
        
        buttons = [
            [Button.text("🔒 लॉगिन करें" if not is_logged_in else "✅ लॉगिन हो गया", resize=True)],
            [Button.text("🌐 कनेक्टेड चैट्स"), Button.text("🤖 नया बॉट जोड़ें")],
            [Button.text("📊 आँकड़े"), Button.text("📣 ब्रॉडकास्ट")]
        ]
        await event.respond("👑 **स्वागत है, मालिक!**\nयह आपका मैनेजर बॉट कंट्रोल पैनल है।", buttons=buttons)
    else:
        # Normal user interface
        me = await bot.get_me()
        buttons = [[Button.url("➕ मुझे एक ग्रुप में जोड़ें ➕", f"https://t.me/{me.username}?startgroup=true")]]
        await event.respond(
            "**नमस्ते!** 👋\n\nमैं एक ग्रुप मैनेजमेंट बॉट हूँ।\n\n"
            "**निर्देश:**\n"
            "1. मुझे अपने ग्रुप में जोड़ने के लिए नीचे दिए गए बटन पर क्लिक करें।\n"
            "2. मुझे पूरे अधिकारों के साथ एडमिन बनाएं।\n"
            "मैं ग्रुप के मालिक को अन्य बॉट्स को प्रबंधित करने में मदद करूँगा।",
            buttons=buttons
        )

@bot.on(events.ChatAction)
async def chat_action_handler(event):
    """Detect when the bot is added to a new group."""
    me = await bot.get_me()
    if event.user_added and event.user_id == me.id:
        chat = await event.get_chat()
        owner = await event.get_user()
        
        await bot.send_message(
            config.OWNER_ID,
            f"✅ **नया ग्रुप जोड़ा गया!**\n\n"
            f"**ग्रुप:** {chat.title} (`{chat.id}`)\n"
            f"**किसने जोड़ा:** {owner.first_name} (@{owner.username or 'N/A'})"
        )
        db.add_connected_chat(chat.id, chat.title)

# --- Owner Command Handlers ---

@bot.on(events.NewMessage(from_users=config.OWNER_ID, func=lambda e: e.is_private))
async def owner_commands_handler(event):
    text = event.raw_text

    owner = db.get_user(config.OWNER_ID)
    if owner and owner.get('state') == 'awaiting_phone':
        phone_match = re.match(r'\+?\d[\d\s-]{8,}\d', text)
        if phone_match:
            await process_login_phone(event, phone_match.group(0).strip())
            return

    if text == "🔒 लॉगिन करें":
        db.update_user_state(config.OWNER_ID, 'awaiting_phone')
        await event.respond(
            "कृपया अपना फ़ोन नंबर भेजें (कंट्री कोड के साथ, जैसे `+919876543210`) या नीचे दिए गए बटन का उपयोग करें।",
            buttons=Button.request_phone("📱 संपर्क साझा करें", resize=True)
        )
    
    elif text == "🌐 कनेक्टेड चैट्स":
        if not user_client: return await event.respond("⚠️ कृपया पहले लॉगिन करें।")
        chats = db.get_connected_chats()
        if not chats: return await event.respond("📭 कोई कनेक्टेड चैट नहीं मिली।")
        
        response = "**🌐 कनेक्टेड चैट्स:**\n\n"
        for chat in chats:
            response += f"• **{chat['title']}** (`{chat['chat_id']}`)\n"
        await event.respond(response)

    elif text == "🤖 नया बॉट जोड़ें":
        if not user_client: return await event.respond("⚠️ कृपया पहले लॉगिन करें।")
        async with bot.conversation(config.OWNER_ID) as conv:
            await conv.send_message("कृपया उस **नए बॉट** का **यूजरनेम** भेजें जिसे आप एडमिन के रूप में जोड़ना चाहते हैं (जैसे, `@NewBot`).")
            new_bot_username = await conv.get_response()
            await add_bot_process(event, new_bot_username.text.strip())

    elif text == "📊 आँकड़े":
        total_users = len(db.get_all_users())
        connected_chats = len(db.get_connected_chats())
        await event.respond(f"**📊 बॉट के आँकड़े:**\n\n"
                            f"👤 **कुल उपयोगकर्ता:** {total_users}\n"
                            f"🌐 **कनेक्टेड चैट्स:** {connected_chats}")

    elif text == "📣 ब्रॉडकास्ट":
        async with bot.conversation(config.OWNER_ID) as conv:
            await conv.send_message("कृपया वह संदेश भेजें जिसे आप सभी उपयोगकर्ताओं को ब्रॉडकास्ट करना चाहते हैं।")
            message_to_broadcast = await conv.get_response()
            
            users = db.get_all_users()
            sent_count = 0
            failed_count = 0
            status_msg = await conv.send_message(f"🚀 {len(users)} उपयोगकर्ताओं को ब्रॉडकास्ट शुरू किया जा रहा है...")
            
            for user in users:
                if user['user_id'] != config.OWNER_ID:
                    try:
                       await bot.send_message(user['user_id'], message_to_broadcast)
                       sent_count += 1
                    except Exception:
                        failed_count += 1
                    await asyncio.sleep(0.1)
            
            await status_msg.edit(f"✅ **ब्रॉडकास्ट पूरा हुआ!**\n\n"
                                  f"📬 **भेजा गया:** {sent_count}\n"
                                  f"❌ **विफल:** {failed_count}")

# --- Login Process ---

@bot.on(events.NewMessage(func=lambda e: e.is_private and e.contact and e.sender_id == config.OWNER_ID))
async def phone_handler_button(event):
    phone = event.message.contact.phone_number
    await process_login_phone(event, phone)

async def process_login_phone(event, phone_number):
    db.update_user_state(config.OWNER_ID, None)
    temp_client = TelegramClient(StringSession(), config.API_ID, config.API_HASH)
    await temp_client.connect()
    
    async with bot.conversation(config.OWNER_ID, timeout=300) as conv:
        try:
            code_request = await temp_client.send_code_request(phone_number)
            await conv.send_message("कृपया टेलीग्राम से प्राप्त ओटीपी भेजें।")
            otp_code = await conv.get_response()
            
            await temp_client.sign_in(phone_number, code=otp_code.text, phone_code_hash=code_request.phone_code_hash)
            
        except Exception as e:
            if "password" in str(e).lower():
                await conv.send_message("आपके खाते में 2FA सक्षम है। कृपया अपना पासवर्ड भेजें।")
                password = await conv.get_response()
                await temp_client.sign_in(password=password.text)
            else:
                await conv.send_message(f"❌ लॉगिन विफल: {e}")
                if temp_client.is_connected(): await temp_client.disconnect()
                return
        
        session_string = temp_client.session.save()
        db.update_session(config.OWNER_ID, session_string)
        if temp_client.is_connected(): await temp_client.disconnect()
        await conv.send_message("✅ **लॉगिन सफल!** Userbot अब सक्रिय है।")
        await initialize_user_client()

# --- Core "Add Bot" Logic ---

async def add_bot_process(event, new_bot_username):
    if not user_client: return await event.respond("⚠️ Userbot active nahi hai. Pehle login karein.")
    chats = db.get_connected_chats()
    total_chats = len(chats)
    if total_chats == 0:
        return await event.respond("प्रक्रिया के लिए कोई कनेक्टेड चैट नहीं है।")

    status_msg = await event.respond(f"🔄 {total_chats} चैट्स के लिए प्रक्रिया शुरू हो रही है...")
    admin_done, admin_failed = 0, 0
    
    admin_rights = ChatAdminRights(
        change_info=True, post_messages=True, edit_messages=True,
        delete_messages=True, ban_users=True, invite_users=True,
        pin_messages=True, add_admins=True, manage_call=True
    )

    for i, chat_info in enumerate(chats):
        chat_id = chat_info['chat_id']
        chat_title = chat_info['title']
        
        if i > 0 and i % 4 == 0:
            try:
                await status_msg.edit(
                    f"**🔄 प्रगति: {i}/{total_chats}**\n\n"
                    f"✅ **सफलतापूर्वक जोड़ा गया:** {admin_done}\n"
                    f"❌ **विफल:** {admin_failed}\n\n"
                    f"अभी प्रोसेस हो रहा है: *{chat_title}*..."
                )
            except: pass
        
        try:
            # **ERROR FIX:** Pehle entity hasil karein
            LOGGER.info(f"Resolving entity for {new_bot_username}")
            new_bot_entity = await user_client.get_entity(new_bot_username)
            
            LOGGER.info(f"Promoting {new_bot_username} in {chat_title}")
            await user_client(EditAdminRequest(
                channel=chat_id,
                user_id=new_bot_entity.id,
                admin_rights=admin_rights,
                rank='bot'
            ))
            
            admin_done += 1
            
        except ChatAdminRequiredError:
            LOGGER.error(f"{chat_title} में विफल: Userbot एडमिन नहीं है या उसके पास अधिकार नहीं हैं।")
            admin_failed += 1
        except Exception as e:
            LOGGER.error(f"{chat_title} में एक अप्रत्याशित त्रुटि हुई: {e}")
            admin_failed += 1
        
        await asyncio.sleep(5) 

    await status_msg.edit(
        f"✅ **प्रक्रिया पूरी हुई!**\n\n"
        f"**कुल चैट्स:** {total_chats}\n"
        f"✅ **सफलतापूर्वक जोड़ा गया:** {admin_done}\n"
        f"❌ **विफल:** {admin_failed}"
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
