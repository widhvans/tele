# database.py
# Handles all interactions with the MongoDB database.

import pymongo
from config import MONGODB_URL

# Establish connection to MongoDB
try:
    client = pymongo.MongoClient(MONGODB_URL)
    db = client.manager_bot_db
    
    # Collections
    users_col = db.users
    chats_col = db.connected_chats
    
    # Create index to avoid duplicate users
    users_col.create_index("user_id", unique=True)
    
    print("✅ Successfully connected to MongoDB.")
except Exception as e:
    print(f"❌ ERROR: Failed to connect to MongoDB: {e}")
    exit(1)

# --- User Functions ---
def add_user(user_id, first_name, username):
    """Adds a new user to the database."""
    try:
        users_col.insert_one({
            "user_id": user_id,
            "first_name": first_name,
            "username": username,
            "session_string": None
        })
    except pymongo.errors.DuplicateKeyError:
        # User already exists
        pass

def get_user(user_id):
    """Retrieves a user's data from the database."""
    return users_col.find_one({"user_id": user_id})

def update_session(user_id, session_string):
    """Updates the session string for a user."""
    users_col.update_one({"user_id": user_id}, {"$set": {"session_string": session_string}})

def get_all_users():
    """Returns a list of all users."""
    return list(users_col.find({}))

# --- Connected Chats Functions ---
def add_connected_chat(chat_id, title):
    """Adds a new connected chat to the database."""
    if not chats_col.find_one({"chat_id": chat_id}):
        chats_col.insert_one({"chat_id": chat_id, "title": title})

def get_connected_chats():
    """Retrieves all connected chats."""
    return list(chats_col.find({}))

def remove_connected_chat(chat_id):
    """Removes a connected chat from the database."""
    chats_col.delete_one({"chat_id": chat_id})
