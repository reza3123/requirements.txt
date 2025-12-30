import asyncio
import os
import logging
from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler
from pyrogram.errors import (
    FloodWait, SessionPasswordNeeded, PhoneCodeInvalid,
    PasswordHashInvalid, PhoneNumberInvalid, PhoneCodeExpired, UserDeactivated, AuthKeyUnregistered
)
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import Flask, request, render_template_string, redirect, session, url_for
from threading import Thread
import random

# --- تنظیمات لاگ‌نویسی ---
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s - %(message)s')

# =======================================================
# ⚠️ تنظیمات اصلی (API_ID و API_HASH خود را اینجا وارد کنید)
# =======================================================
API_ID = 38765800
API_HASH = "1323474b4b6fc4d0b1b3b15eafd30c7b"
# ⚠️ شماره تلفن مجاز برای ورود را اینجا با کد کشور وارد کنید
ALLOWED_PHONE_NUMBER = "+989900223642" 

# --- متغیرهای برنامه ---
TEHRAN_TIMEZONE = ZoneInfo("Asia/Tehran")
app_flask = Flask(name)
app_flask.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

# --- دیکشنری فونت‌ها برای ساعت ---
FONT_STYLES = {
    "cursive":      {'0':'𝟎','1':'𝟏','2':'𝟐','3':'𝟑','4':'𝟒','5':'𝟓','6':'𝟔','7':'𝟕','8':'𝟖','9':'𝟗',':':':'},
    "stylized":     {'0':'𝟬','1':'𝟭','2':'𝟮','3':'𝟯','4':'𝟰','5':'𝟱','6':'𝟲','7':'𝟳','8':'𝟴','9':'𝟵',':':':'},
    "doublestruck": {'0':'𝟘','1':'𝟙','2':'𝟚','3':'𝟛','4':'𝟜','5':'𝟝','6':'𝟞','7':'𝟟','8':'𝟠','9':'𝟡',':':':'},
    "monospace":    {'0':'𝟶','1':'𝟷','2':'𝟸','3':'𝟹','4':'𝟺','5':'𝟻','6':'𝟼','7':'𝟽','8':'𝟾','9':'𝟿',':':':'},
    "normal":       {'0':'0','1':'1','2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',':':':'},
}
ALL_DIGITS = "".join(set(char for font in FONT_STYLES.values() for char in font.values()))

# --- متغیرهای مربوط به قابلیت‌ها ---
ENEMY_REPLIES = [
    "متن ۱", "متن ۲", "متن ۳", "متن ۴", "متن ۵",
    "متن ۶", "متن ۷", "متن ۸", "متن ۹", "متن ۱۰",
]
OFFLINE_REPLY_MESSAGE = "سلام! در حال حاضر آفلاین هستم و پیام شما را دریافت کردم. در اولین فرصت پاسخ خواهم داد. ممنون از پیامتون."

# --- مدیریت وضعیت کاربران (بر اساس ID کاربر) ---
ACTIVE_ENEMIES = {}
ENEMY_REPLY_QUEUES = {}
OFFLINE_MODE_STATUS = {}
USERS_REPLIED_IN_OFFLINE = {}


EVENT_LOOP = asyncio.new_event_loop()
ACTIVE_CLIENTS = {}
ACTIVE_BOTS = {}

# --- توابع اصلی ربات ---
def stylize_time(time_str: str, style: str) -> str:
    font_map = FONT_STYLES.get(style, FONT_STYLES["stylized"])
    return ''.join(font_map.get(char, char) for char in time_str)

async def update_profile_clock(client: Client, user_id: int, font_style: str, disable_clock: bool = False):
    """حلقه اصلی که ربات را زنده نگه می‌دارد و در صورت فعال بودن، ساعت را آپدیت می‌کند."""
    log_message = "without clock updates" if disable_clock else f"with font '{font_style}'"
    logging.info(f"Starting bot loop for user_id {user_id} {log_message}...")
    while user_id in ACTIVE_BOTS:
        try:
            if not disable_clock:
                me = await client.get_me()
                current_name = me.first_name
                
                parts = current_name.rsplit(' ', 1)
                base_name = parts[0].strip() if len(parts) > 1 and ':' in parts[-1] and any(char in ALL_DIGITS for char in parts[-1]) else current_name.strip()
              tehran_time = datetime.now(TEHRAN_TIMEZONE)
                current_time_str = tehran_time.strftime("%H:%M")
                stylized_time = stylize_time(current_time_str, font_style)
                new_name = f"{base_name} {stylized_time}"
                
                if new_name != current_name:
                    await client.update_profile(first_name=new_name)
            
            now = datetime.now(TEHRAN_TIMEZONE)
            sleep_duration = 60 - now.second + 0.1
            await asyncio.sleep(sleep_duration)
        except (UserDeactivated, AuthKeyUnregistered):
            logging.error(f"Session for user_id {user_id} is invalid. Stopping bot.")
            break
        except FloodWait as e:
            logging.warning(f"Flood wait of {e.value}s for user_id {user_id}.")
            await asyncio.sleep(e.value + 5)
        except Exception as e:
            logging.error(f"An error occurred in the main loop for user_id {user_id}: {e}", exc_info=True)
            await asyncio.sleep(60)
    
    if client.is_connected:
        await client.stop()
    ACTIVE_BOTS.pop(user_id, None)
    ACTIVE_ENEMIES.pop(user_id, None)
    OFFLINE_MODE_STATUS.pop(user_id, None)
    ENEMY_REPLY_QUEUES.pop(user_id, None)
    USERS_REPLIED_IN_OFFLINE.pop(user_id, None)
    logging.info(f"Bot for user_id {user_id} has been stopped and cleaned up.")

# --- هندلرهای قابلیت‌ها ---
async def enemy_handler(client, message):
    user_id = client.me.id
    if user_id not in ENEMY_REPLY_QUEUES or not ENEMY_REPLY_QUEUES[user_id]:
        shuffled_replies = random.sample(ENEMY_REPLIES, len(ENEMY_REPLIES))
        ENEMY_REPLY_QUEUES[user_id] = shuffled_replies
    reply_text = ENEMY_REPLY_QUEUES[user_id].pop(0)
    try:
        await message.reply_text(reply_text)
    except Exception as e:
        logging.warning(f"Could not reply to enemy for user_id {user_id}: {e}")

async def enemy_controller(client, message):
    if not message.reply_to_message or not message.reply_to_message.from_user: return
    user_id = client.me.id
    target_user = message.reply_to_message.from_user
    chat_id = message.chat.id
    command = message.text.strip()
    if user_id not in ACTIVE_ENEMIES:
        ACTIVE_ENEMIES[user_id] = set()
    if command == "دشمن فعال":
        ACTIVE_ENEMIES[user_id].add((target_user.id, chat_id))
        await message.edit_text(f"✅ حالت دشمن برای {target_user.first_name} در این چت فعال شد.")
    elif command == "دشمن خاموش":
        ACTIVE_ENEMIES[user_id].discard((target_user.id, chat_id))
        await message.edit_text(f"❌ حالت دشمن برای {target_user.first_name} در این چت خاموش شد.")

async def offline_mode_controller(client, message):
    user_id = client.me.id
    command = message.text.strip()
    if command == "افلاین روشن":
        OFFLINE_MODE_STATUS[user_id] = True
        USERS_REPLIED_IN_OFFLINE[user_id] = set()
        await message.edit_text("✅ حالت آفلاین فعال شد. به هر کاربر فقط یک بار پاسخ داده می‌شود.")
    elif command == "افلاین خاموش":
        OFFLINE_MODE_STATUS[user_id] = False
        await message.edit_text("❌ حالت آفلاین غیرفعال شد.")

async def offline_auto_reply_handler(client, message):
    owner_user_id = client.me.id
    target_user_id = message.from_user.id
    if OFFLINE_MODE_STATUS.get(owner_user_id, False):
        replied_users = USERS_REPLIED_IN_OFFLINE.get(owner_user_id, set())
        if target_user_id in replied_users:
            return
        try:
            await message.reply_text(OFFLINE_REPLY_MESSAGE)
            replied_users.add(target_user_id)
            USERS_REPLIED_IN_OFFLINE[owner_user_id] = replied_users
        except Exception as e:
            logging.warning(f"Could not auto-reply for user_id {owner_user_id}: {e}")

async def is_enemy_filter(_, client, message):
    if not message.from_user: return False
    user_id = client.me.id
    if user_id not in ACTIVE_ENEMIES: return False
    return (message.from_user.id, message.chat.id) in ACTIVE_ENEMIES.get(user_id, set())

is_enemy = filters.create(is_enemy_filter)
async def start_bot_instance(session_string: str, phone: str, font_style: str, disable_clock: bool = False):
    try:
        client = Client(f"bot_{phone}", api_id=API_ID, api_hash=API_HASH, session_string=session_string)
        await client.start()
        user_id = client.me.id
        if user_id in ACTIVE_BOTS:
            task = ACTIVE_BOTS.pop(user_id, None)
            if task: task.cancel()
            await asyncio.sleep(1)
        
        client.add_handler(MessageHandler(enemy_controller, filters.text & filters.reply & filters.me & filters.regex("^(دشمن فعال|دشمن خاموش)$")), group=0)
        client.add_handler(MessageHandler(offline_mode_controller, filters.text & filters.me & filters.regex("^(افلاین روشن|افلاین خاموش)$")), group=0)
        client.add_handler(MessageHandler(enemy_handler, is_enemy & ~filters.me), group=1)
        client.add_handler(MessageHandler(offline_auto_reply_handler, filters.private & ~filters.me), group=1)

        task = asyncio.create_task(update_profile_clock(client, user_id, font_style, disable_clock))
        ACTIVE_BOTS[user_id] = task
        log_message = "WITHOUT CLOCK" if disable_clock else "WITH CLOCK"
        logging.info(f"Successfully started bot instance {log_message} for user_id {user_id}.")
    except Exception as e:
        logging.error(f"FAILED to start bot instance for {phone}: {e}", exc_info=True)

HTML_TEMPLATE = """
<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>سلف بات ساعت تلگرام</title><style>@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700&display=swap');body{font-family:'Vazirmatn',sans-serif;background-color:#f0f2f5;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;padding:20px;box-sizing:border-box;}.container{background:white;padding:30px 40px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.1);text-align:center;width:100%;max-width:480px;}h1{color:#333;margin-bottom:20px;font-size:1.5em;}p{color:#666;line-height:1.6;}form{display:flex;flex-direction:column;gap:15px;margin-top:20px;}input[type="tel"],input[type="text"],input[type="password"]{padding:12px;border:1px solid #ddd;border-radius:8px;font-size:16px;text-align:left;direction:ltr;}button{padding:12px;background-color:#007bff;color:white;border:none;border-radius:8px;font-size:16px;cursor:pointer;transition:background-color .2s;}.error{color:#d93025;margin-top:15px;font-weight:bold;}label{font-weight:bold;color:#555;display:block;margin-bottom:5px;text-align:right;}.font-options{border:1px solid #ddd;border-radius:8px;overflow:hidden;}.font-option{display:flex;align-items:center;padding:12px;border-bottom:1px solid #ddd;cursor:pointer;}.font-option:last-child{border-bottom:none;}.font-option input[type="radio"]{margin-left:15px;}.font-option label{display:flex;justify-content:space-between;align-items:center;width:100%;font-weight:normal;cursor:pointer;}.font-option .preview{font-size:1.3em;font-weight:bold;direction:ltr;color:#0056b3;}.success{color:#1e8e3e;}.checkbox-option{display:flex;align-items:center;justify-content:flex-end;gap:10px;margin-top:10px;padding:8px;background-color:#f8f9fa;border-radius:8px;}.checkbox-option label{margin-bottom:0;font-weight:normal;cursor:pointer;color:#444;}</style></head><body><div class="container">
async def start_bot_instance(session_string: str, phone: str, font_style: str, disable_clock: bool = False):
    try:
        client = Client(f"bot_{phone}", api_id=API_ID, api_hash=API_HASH, session_string=session_string)
        await client.start()
        user_id = client.me.id
        if user_id in ACTIVE_BOTS:
            task = ACTIVE_BOTS.pop(user_id, None)
            if task: task.cancel()
            await asyncio.sleep(1)
        
        client.add_handler(MessageHandler(enemy_controller, filters.text & filters.reply & filters.me & filters.regex("^(دشمن فعال|دشمن خاموش)$")), group=0)
        client.add_handler(MessageHandler(offline_mode_controller, filters.text & filters.me & filters.regex("^(افلاین روشن|افلاین خاموش)$")), group=0)
        client.add_handler(MessageHandler(enemy_handler, is_enemy & ~filters.me), group=1)
        client.add_handler(MessageHandler(offline_auto_reply_handler, filters.private & ~filters.me), group=1)

        task = asyncio.create_task(update_profile_clock(client, user_id, font_style, disable_clock))
        ACTIVE_BOTS[user_id] = task
        log_message = "WITHOUT CLOCK" if disable_clock else "WITH CLOCK"
        logging.info(f"Successfully started bot instance {log_message} for user_id {user_id}.")
    except Exception as e:
        logging.error(f"FAILED to start bot instance for {phone}: {e}", exc_info=True)

HTML_TEMPLATE = """
<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>سلف بات ساعت تلگرام</title><style>@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700&display=swap');body{font-family:'Vazirmatn',sans-serif;background-color:#f0f2f5;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;padding:20px;box-sizing:border-box;}.container{background:white;padding:30px 40px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.1);text-align:center;width:100%;max-width:480px;}h1{color:#333;margin-bottom:20px;font-size:1.5em;}p{color:#666;line-height:1.6;}form{display:flex;flex-direction:column;gap:15px;margin-top:20px;}input[type="tel"],input[type="text"],input[type="password"]{padding:12px;border:1px solid #ddd;border-radius:8px;font-size:16px;text-align:left;direction:ltr;}button{padding:12px;background-color:#007bff;color:white;border:none;border-radius:8px;font-size:16px;cursor:pointer;transition:background-color .2s;}.error{color:#d93025;margin-top:15px;font-weight:bold;}label{font-weight:bold;color:#555;display:block;margin-bottom:5px;text-align:right;}.font-options{border:1px solid #ddd;border-radius:8px;overflow:hidden;}.font-option{display:flex;align-items:center;padding:12px;border-bottom:1px solid #ddd;cursor:pointer;}.font-option:last-child{border-bottom:none;}.font-option input[type="radio"]{margin-left:15px;}.font-option label{display:flex;justify-content:space-between;align-items:center;width:100%;font-weight:normal;cursor:pointer;}.font-option .preview{font-size:1.3em;font-weight:bold;direction:ltr;color:#0056b3;}.success{color:#1e8e3e;}.checkbox-option{display:flex;align-items:center;justify-content:flex-end;gap:10px;margin-top:10px;padding:8px;background-color:#f8f9fa;border-radius:8px;}.checkbox-option label{margin-bottom:0;font-weight:normal;cursor:pointer;color:#444;}</style></head><body><div class="container">
{% if step == 'GET_PHONE' %}<h1>ورود به سلف بات</h1><p>شماره و تنظیمات خود را انتخاب کنید تا ربات فعال شود.</p>{% if error_message %}<p class="error">{{ error_message }}</p>{% endif %}<form action="{{ url_for('login') }}" method="post"><input type="hidden" name="action" value="phone"><div><label for="phone">شماره تلفن (با کد کشور)</label><input type="tel" id="phone" name="phone_number" placeholder="+989123456789" required autofocus></div><div><label>استایل فونت ساعت</label><div class="font-options">{% for name, data in font_previews.items() %}<div class="font-option" onclick="document.getElementById('font-{{ data.style }}').checked = true;"><input type="radio" name="font_style" value="{{ data.style }}" id="font-{{ data.style }}" {% if loop.first %}checked{% endif %}><label for="font-{{ data.style }}"><span>{{ name }}</span><span class="preview">{{ data.preview }}</span></label></div>{% endfor %}</div></div><div class="checkbox-option"><input type="checkbox" id="disable_clock" name="disable_clock"><label for="disable_clock">فعال‌سازی بدون ساعت</label></div><button type="submit">ارسال کد تایید</button></form>
{% elif step == 'GET_CODE' %}<h1>کد تایید</h1><p>کدی به تلگرام شما با شماره <strong>{{ phone_number }}</strong> ارسال شد.</p>{% if error_message %}<p class="error">{{ error_message }}</p>{% endif %}<form action="{{ url_for('login') }}" method="post"><input type="hidden" name="action" value="code"><input type="text" name="code" placeholder="Verification Code" required><button type="submit">تایید کد</button></form>
{% elif step == 'GET_PASSWORD' %}<h1>رمز دو مرحله‌ای</h1><p>حساب شما نیاز به رمز تایید دو مرحله‌ای دارد.</p>{% if error_message %}<p class="error">{{ error_message }}</p>{% endif %}<form action="{{ url_for('login') }}" method="post"><input type="hidden" name="action" value="password"><input type="password" name="password" placeholder="2FA Password" required><button type="submit">ورود</button></form>
{% elif step == 'SHOW_SUCCESS' %}<h1 class="success">✅ ربات فعال شد!</h1><p>ربات با موفقیت برای شما فعال شد. تا زمانی که این سایت باز باشد، ربات شما نیز کار خواهد کرد.</p><form action="{{ url_for('home') }}" method="get" style="margin-top: 20px;"><button type="submit">ورود با شماره جدید</button></form>{% endif %}</div></body></html>
"""

def get_font_previews():
    sample_time = "12:34"
    return { "کشیده": {"style": "cursive", "preview": stylize_time(sample_time, "cursive")}, "فانتزی": {"style": "stylized", "preview": stylize_time(sample_time, "stylized")}, "توخالی": {"style": "doublestruck", "preview": stylize_time(sample_time, "doublestruck")}, "کامپیوتری": {"style": "monospace", "preview": stylize_time(sample_time, "monospace")}, "ساده": {"style": "normal", "preview": stylize_time(sample_time, "normal")} }

async def cleanup_client(phone):
    client = ACTIVE_CLIENTS.pop(phone, None)
    if client and client.is_connected:
        await client.disconnect()

@app_flask.route('/')
def home():
    session.clear()
    return render_template_string(HTML_TEMPLATE, step='GET_PHONE', font_previews=get_font_previews())

@app_flask.route('/login', methods=['POST'])
def login():
    action = request.form.get('action')
    phone = session.get('phone_number')
    try:
        if action == 'phone':
            phone = request.form.get('phone_number').strip()
            if ALLOWED_PHONE_NUMBER and phone != ALLOWED_PHONE_NUMBER:
                return render_template_string(HTML_TEMPLATE, step='GET_PHONE', 
                                              error_message="شما مجاز به استفاده از این ربات نیستید.", 
                                              font_previews=get_font_previews())
                                              session['phone_number'] = phone
            session['font_style'] = request.form.get('font_style')
            session['disable_clock'] = 'on' == request.form.get('disable_clock')
            asyncio.run_coroutine_threadsafe(send_code_task(phone), EVENT_LOOP).result(45)
            return render_template_string(HTML_TEMPLATE, step='GET_CODE', phone_number=phone)
        elif action == 'code':
            next_step = asyncio.run_coroutine_threadsafe(sign_in_task(phone, request.form.get('code')), EVENT_LOOP).result(45)
            if next_step == 'GET_PASSWORD':
                return render_template_string(HTML_TEMPLATE, step='GET_PASSWORD', phone_number=phone)
            return render_template_string(HTML_TEMPLATE, step='SHOW_SUCCESS')
        elif action == 'password':
            asyncio.run_coroutine_threadsafe(check_password_task(phone, request.form.get('password')), EVENT_LOOP).result(45)
            return render_template_string(HTML_TEMPLATE, step='SHOW_SUCCESS')
    except Exception as e:
        if phone: asyncio.run_coroutine_threadsafe(cleanup_client(phone), EVENT_LOOP)
        logging.error(f"Error during '{action}': {e}", exc_info=True)
        error_msg, current_step = "An unexpected error occurred.", 'GET_PHONE'
        if isinstance(e, (PhoneCodeInvalid, PasswordHashInvalid)):
            current_step = 'GET_CODE' if isinstance(e, PhoneCodeInvalid) else 'GET_PASSWORD'
            error_msg = "کد یا رمز وارد شده اشتباه است."
        elif isinstance(e, (PhoneNumberInvalid, TypeError)): error_msg = "شماره تلفن نامعتبر است."
        elif isinstance(e, PhoneCodeExpired): error_msg = "کد تایید منقضی شده، دوباره تلاش کنید."
        elif isinstance(e, FloodWait): error_msg = f"محدودیت تلگرام. لطفا {e.value} ثانیه دیگر تلاش کنید."
        if current_step == 'GET_PHONE': session.clear()
        return render_template_string(HTML_TEMPLATE, step=current_step, error_message=error_msg, phone_number=phone, font_previews=get_font_previews())
    return redirect(url_for('home'))

async def send_code_task(phone):
    await cleanup_client(phone)
    client = Client(f"user_{phone}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
    ACTIVE_CLIENTS[phone] = client
    await client.connect()
    sent_code = await client.send_code(phone)
    session['phone_code_hash'] = sent_code.phone_code_hash

async def sign_in_task(phone, code):
    client = ACTIVE_CLIENTS.get(phone)
    if not client: raise Exception("Session expired.")
    try:
        await client.sign_in(phone, session['phone_code_hash'], code)
        session_str = await client.export_session_string()
        await start_bot_instance(session_str, phone, session.get('font_style'), session.get('disable_clock', False))
        await cleanup_client(phone)
        return None
    except SessionPasswordNeeded:
        return 'GET_PASSWORD'

async def check_password_task(phone, password):
    client = ACTIVE_CLIENTS.get(phone)
    if not client: raise Exception("Session expired.")
    try:
        await client.check_password(password)
        session_str = await client.export_session_string()
        await start_bot_instance(session_str, phone, session.get('font_style'), session.get('disable_clock', False))
    finally:
        await cleanup_client(phone)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

def run_asyncio_loop():
    try:
        EVENT_LOOP.run_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        EVENT_LOOP.close()

if name == "main":
    logging.info("Starting Telegram Clock Bot Service...")
    loop_thread = Thread(target=run_asyncio_loop, daemon=True)
    loop_thread.start()
    run_flask()
    
