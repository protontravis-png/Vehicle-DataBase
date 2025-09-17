import os
import asyncio
import requests
from bs4 import BeautifulSoup
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import UserIsBlocked, PeerIdInvalid, Timeout
from pymongo import MongoClient
from urllib.parse import quote_plus

# ------------------- #
# CONFIGURATION       #
# ------------------- #
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # Your Telegram User ID

# Constants
INITIAL_CREDITS = 5
REFERRAL_BONUS = 10
LOOKUP_COST = 1

# Initialize the bot
app = Client(
    "vehicle_info_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Initialize MongoDB Client
mongo_client = MongoClient(MONGO_URI)
db = mongo_client.vehicle_bot
users_collection = db.users
user_states = {} # To manage conversation states

# ------------------- #
# DATABASE HELPERS    #
# ------------------- #
def add_user_to_db(user_id: int, first_name: str, referred_by: int = None):
    if users_collection.find_one({"user_id": user_id}): return
    users_collection.insert_one({
        "user_id": user_id, "first_name": first_name, "credits": INITIAL_CREDITS,
        "referred_by": referred_by, "referrals": 0, "lookups_done": 0,
        "is_banned": False, "is_premium": False
    })
    if referred_by:
        users_collection.update_one({"user_id": referred_by}, {"$inc": {"credits": REFERRAL_BONUS, "referrals": 1}})

def get_user(user_id: int):
    return users_collection.find_one({"user_id": user_id})

def use_credit(user_id: int):
    user = get_user(user_id)
    if user and user.get("is_premium"):
        users_collection.update_one({"user_id": user_id}, {"$inc": {"lookups_done": 1}})
    else:
        users_collection.update_one({"user_id": user_id}, {"$inc": {"credits": -LOOKUP_COST, "lookups_done": 1}})

# ------------------- #
# VEHICLE INFO FETCHER#
# ------------------- #
def get_vehicle_details(rc_number: str) -> dict:
    """Fetches comprehensive vehicle details from vahanx.in."""
    rc = rc_number.strip().upper()
    url = f"https://vahanx.in/rc-search/{rc}"

    headers = {
        "Host": "vahanx.in",
        "Connection": "keep-alive",
        "sec-ch-ua": "\"Chromium\";v=\"130\", \"Google Chrome\";v=\"130\", \"Not?A_Brand\";v=\"99\"",
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": "\"Android\"",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Referer": "https://vahanx.in/rc-search",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9"
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
    except requests.exceptions.RequestException as e:
        return {"error": f"Network error: {e}"}
    except Exception as e:
        return {"error": str(e)}

    def get_value(label):
        try:
            div = soup.find("span", string=label).find_parent("div")
            return div.find("p").get_text(strip=True)
        except AttributeError:
            return None

    data = {
        "Owner Name": get_value("Owner Name"),
        "Father's Name": get_value("Father's Name"),
        "Owner Serial No": get_value("Owner Serial No"),
        "Model Name": get_value("Model Name"),
        "Maker Model": get_value("Maker Model"),
        "Vehicle Class": get_value("Vehicle Class"),
        "Fuel Type": get_value("Fuel Type"),
        "Fuel Norms": get_value("Fuel Norms"),
        "Registration Date": get_value("Registration Date"),
        "Insurance Company": get_value("Insurance Company"),
        "Insurance No": get_value("Insurance No"),
        "Insurance Expiry": get_value("Insurance Expiry"),
        "Insurance Upto": get_value("Insurance Upto"),
        "Fitness Upto": get_value("Fitness Upto"),
        "Tax Upto": get_value("Tax Upto"),
        "PUC No": get_value("PUC No"),
        "PUC Upto": get_value("PUC Upto"),
        "Financier Name": get_value("Financier Name"),
        "Registered RTO": get_value("Registered RTO"),
        "Address": get_value("Address"),
        "City Name": get_value("City Name"),
        "Phone": get_value("Phone"),
        "Owner": "@NGYT777GG"
    }
    return data

# ------------------- #
# MAIN MENU & FILTERS #
# ------------------- #

async def send_main_menu(message_or_query):
    user = message_or_query.from_user
    welcome_text = f"👋 Welcome back, {user.first_name}!\nYour account is ready to use."
    keyboard = [
        [InlineKeyboardButton("🔍 Vehicle Lookup", callback_data="lookup")],
        [InlineKeyboardButton("👥 Referral System", callback_data="referral"), InlineKeyboardButton("💰 My Credits", callback_data="credits")],
        [InlineKeyboardButton("📊 Statistics", callback_data="stats"), InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    if user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    if isinstance(message_or_query, Message):
        await message_or_query.reply_text(welcome_text, reply_markup=reply_markup)
    else:
        await message_or_query.message.edit_text(welcome_text, reply_markup=reply_markup)

# ------------------- #
# USER HANDLERS       #
# ------------------- #
@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    user = message.from_user
    referred_by = int(message.command[1]) if len(message.command) > 1 and message.command[1].isdigit() else None
    add_user_to_db(user.id, user.first_name, referred_by)
    await send_main_menu(message)

@app.on_message(filters.command("ban"))
async def ban_command(client: Client, message: Message):
    await user_action_command(client, message, "ban")

@app.on_message(filters.command("unban"))
async def unban_command(client: Client, message: Message):
    await user_action_command(client, message, "unban")

@app.on_message(filters.command("premium"))
async def premium_command(client: Client, message: Message):
    await user_action_command(client, message, "premium")

@app.on_message(filters.command("unpremium"))
async def unpremium_command(client: Client, message: Message):
    await user_action_command(client, message, "unpremium")

@app.on_message(filters.command("addcredit"))
async def add_credit_command(client: Client, message: Message):
    if message.from_user.id != ADMIN_ID: return
    if len(message.command) < 3 or not message.command[1].isdigit() or not message.command[2].isdigit():
        return await message.reply_text("Usage: `/addcredit <user_id> <amount>`")
    
    target_id, amount = int(message.command[1]), int(message.command[2])
    if not get_user(target_id):
        return await message.reply_text(f"❌ User `{target_id}` not found.")
        
    users_collection.update_one({"user_id": target_id}, {"$inc": {"credits": amount}})
    await message.reply_text(f"✅ Added `{amount}` credits to user `{target_id}`.")

@app.on_message(filters.command("broadcast"))
async def broadcast_command(client: Client, message: Message):
    if message.from_user.id != ADMIN_ID: return
    if not message.reply_to_message:
        return await message.reply_text("Reply to a message to broadcast it.")

    msg = await message.reply_text("📢 Broadcasting...")
    sent, failed = 0, 0
    for u in users_collection.find({"is_banned": False}):
        try:
            await message.reply_to_message.copy(u['user_id'])
            sent += 1
        except (UserIsBlocked, PeerIdInvalid):
            failed += 1
        await asyncio.sleep(0.1)
    await msg.edit_text(f"✅ Broadcast complete!\nSent: {sent}\nFailed: {failed}")

@app.on_message(filters.text)
async def vehicle_info_handler(client: Client, message: Message):
    user_id = message.from_user.id

    # Only process vehicle numbers if the user is in the correct state
    if user_states.get(user_id) != "awaiting_vehicle_number":
        return

    # Clear the state to prevent re-processing
    user_states.pop(user_id, None)

    user = get_user(user_id)
    if not user:
        add_user_to_db(user_id, message.from_user.first_name)
        user = get_user(user_id)

    if user.get("is_banned"): return await message.reply_text("❌ You are banned.")
    if not user.get("is_premium") and user.get("credits", 0) < LOOKUP_COST: return await message.reply_text("❌ Out of Credits! Refer friends.")

    rc_number = message.text
    msg = await message.reply_text(f"🔍 Searching for `{rc_number}`...")
    details = get_vehicle_details(rc_number)

    if details.get("error") or not any(v and v != "N/A" for v in details.values()):
        return await msg.edit_text(f"❌ No details found for `{rc_number}`.")

    use_credit(user_id)
    user = get_user(user_id)
    new_credits = "Unlimited" if user.get("is_premium") else user.get("credits", 0)

    response = f"**✅ Details for `{rc_number.upper()}`**\n\n" + "\n".join([f"**{k}:** `{v}`" for k, v in details.items() if v and v != "N/A"])
    response += f"\n\n---\n**Credits: {new_credits}**"
    await msg.edit_text(response)

# ------------------- #
# ADMIN COMMANDS      #
# ------------------- #
async def user_action_command(client: Client, message: Message, action: str):
    if message.from_user.id != ADMIN_ID: return
    if len(message.command) < 2 or not message.command[1].isdigit():
        return await message.reply_text(f"Usage: `/{action} <user_id>`")
    
    target_id = int(message.command[1])
    target_user = get_user(target_id)

    if not target_user:
        return await message.reply_text(f"❌ User `{target_id}` not found.")

    action_map = {
        "ban": {"is_banned": True}, "unban": {"is_banned": False},
        "premium": {"is_premium": True}, "unpremium": {"is_premium": False}
    }
    
    users_collection.update_one({"user_id": target_id}, {"$set": action_map[action]})
    await message.reply_text(f"✅ User `{target_id}` has been updated.")




# ------------------- #
# CALLBACK HANDLERS   #
# ------------------- #
@app.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    data = query.data
    user_id = query.from_user.id
    user = get_user(user_id)

    if not user:
        add_user_to_db(user_id, query.from_user.first_name)
        user = get_user(user_id)

    back_button = InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")
    admin_back_button = InlineKeyboardButton("⬅️ Back to Admin", callback_data="admin_panel")

    if data == "lookup":
        await query.message.edit_text("➡️ Send a vehicle number.", reply_markup=InlineKeyboardMarkup([[back_button]]))
        user_states[user_id] = "awaiting_vehicle_number"
    elif data == "referral":
        link = f"https://t.me/{(await client.get_me()).username}?start={user_id}"
        await query.message.edit_text(f"**👥 Referral System 👥**\n\nInvite friends, earn **{REFERRAL_BONUS} credits**!\n\nYour link: `{link}`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Share", url=f"https://t.me/share/url?url={quote_plus(link)}&text=...")], [back_button]]))
    elif data == "credits": await query.message.edit_text(f"💰 **My Credits** 💰\n\nYou have **{'Unlimited' if user.get('is_premium') else user.get('credits', 0)}** credits.", reply_markup=InlineKeyboardMarkup([[back_button]]))
    elif data == "stats": await query.message.edit_text(f"📊 **Your Stats** 📊\n\n**Referred:** `{user.get('referrals', 0)}`\n**Lookups:** `{user.get('lookups_done', 0)}`", reply_markup=InlineKeyboardMarkup([[back_button]]))
    elif data == "help": await query.message.edit_text("ℹ️ **Help** ℹ️\n\n- Use the buttons to navigate.\n- Send a vehicle number to get details.", reply_markup=InlineKeyboardMarkup([[back_button]]))
    elif data == "back_to_main": await send_main_menu(query)
    
    # Admin Callbacks
    elif data == "admin_panel" and user_id == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("📈 Full Statistics", callback_data="admin_stats")],
            [back_button]
        ]
        await query.message.edit_text(
            "👑 **Admin Panel** 👑\n\n"
            "Admin actions are now command-based:\n"
            "`/ban <user_id>`\n`/unban <user_id>`\n"
            "`/premium <user_id>`\n`/unpremium <user_id>`\n"
            "`/addcredit <user_id> <amount>`\n"
            "`/broadcast` (reply to a message)",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data == "admin_stats" and user_id == ADMIN_ID:
        stats = {
            "Total Users": users_collection.count_documents({}), "Banned": users_collection.count_documents({"is_banned": True}),
            "Premium": users_collection.count_documents({"is_premium": True}), "Total Lookups": sum(u.get('lookups_done', 0) for u in users_collection.find({}))
        }
        await query.message.edit_text("📈 **Full Bot Stats** 📈\n\n" + "\n".join([f"**{k}:** `{v}`" for k, v in stats.items()]), reply_markup=InlineKeyboardMarkup([[admin_back_button]]))


    await query.answer()

# ------------------- #
# BOT EXECUTION       #
# ------------------- #
if __name__ == "__main__":
    print("Bot is starting with Interactive Admin Panel...")
    app.run()
    print("Bot has stopped.")