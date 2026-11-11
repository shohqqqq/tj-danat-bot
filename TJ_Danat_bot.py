# -*- coding: utf-8 -*-
# TJ_Danat_bot.py — PRO VERSION
# Requires: python-telegram-bot==13.15
# Put your token into BOT_TOKEN environment variable (do NOT put token directly in code)

import os
import time
import json
import logging
from datetime import datetime
from functools import wraps
from threading import Lock

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler, CallbackContext

# ---------------- CONFIG ----------------
BOT_TOKEN = os.getenv("9258175656:AAEOBaVPmPLFcKd_UAuHj_FDYLGzOFVu5HI")
if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN environment variable before running the bot.")

ADMIN_ID = 7234237886
DATA_DIR = "data"
USERS_FILE = os.path.join(DATA_DIR, "users.json")
SALES_FILE = os.path.join(DATA_DIR, "sales.json")
LOG_FILE = os.path.join(DATA_DIR, "bot.log")

PRICES = {"100":11,"310":31,"520":53,"1060":103,"1270":43}
VOUCHER_WEEK = 18
VOUCHER_MONTH = 115
PAY_NUMBER = "783082010"
SPAM_INTERVAL = 5

# ---------------- Logging ----------------
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ---------------- Simple JSON DB ----------------
lock = Lock()
def read_json(path, default):
    with lock:
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)
            return default
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except:
                return default

def write_json(path, data):
    with lock:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

users_db = read_json(USERS_FILE, {})   # key: str(uid) -> {lang,last_action,last_time}
sales_db = read_json(SALES_FILE, [])   # list of sales

# ---------------- Anti-spam decorator ----------------
last_ts = {}
def anti_spam(func):
    @wraps(func)
    def wrapper(update: Update, context: CallbackContext, *a, **kw):
        uid = update.effective_user.id if update.effective_user else None
        if uid:
            now = time.time()
            last = last_ts.get(uid, 0)
            if now - last < SPAM_INTERVAL:
                try:
                    update.message.reply_text("⏳ Илтимос, бир неча сониядан кейин қайта уриниб кўринг.")
                except:
                    pass
                return
            last_ts[uid] = now
        return func(update, context, *a, **kw)
    return wrapper

# ---------------- Translations ----------------
TEXTS = {
 "start":{"tj":"💎 Салом! Лутфан забонро интихоб кунед:","uz":"💎 Salom! Iltimos tilni tanlang:","ru":"💎 Привет! Выберите язык:"},
 "menu":{"tj":"Лутфан танланг:","uz":"Iltimos tanlang:","ru":"Пожалуйста, выберите:"}
}
def tx(key, lang): return TEXTS.get(key,{}).get(lang, TEXTS.get(key,{}).get("ru",""))

# ---------------- Helpers ----------------
def get_lang(uid): return users_db.get(str(uid),{}).get("lang","tj")
def set_lang(uid, lang):
    users_db.setdefault(str(uid),{})
    users_db[str(uid)]["lang"]=lang
    write_json(USERS_FILE, users_db)
def set_last_action(uid, action):
    users_db.setdefault(str(uid),{})
    users_db[str(uid)]["last_action"]=action
    users_db[str(uid)]["last_time"]=int(time.time())
    write_json(USERS_FILE, users_db)
def log_sale(rec):
    sales_db.append(rec); write_json(SALES_FILE, sales_db)

# ---------------- Start & language keyboard ----------------
def lang_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Тоҷикӣ 🇹🇯",callback_data="lang_tj"),
                                  InlineKeyboardButton("O‘zbek 🇺🇿",callback_data="lang_uz")],
                                 [InlineKeyboardButton("Русский 🇷🇺",callback_data="lang_ru")]])

@anti_spam
def start_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(tx("start","tj"), reply_markup=lang_kb())

def lang_cb(update: Update, context: CallbackContext):
    q = update.callback_query; q.answer()
    lang = q.data.split("_")[-1] if "_" in q.data else "tj"
    if lang not in ("tj","uz","ru"): lang="tj"
    set_lang(q.from_user.id, lang)
    send_main_menu(q.from_user.id, context, welcome=True)

def send_main_menu(uid, context: CallbackContext, welcome=False):
    lang = get_lang(uid)
    text = tx("start","tj") if welcome else tx("menu",lang)
    if lang=="tj":
        kb = ReplyKeyboardMarkup([["🛒 Хариди алмазҳо","🎫 Ваучерҳо"],["📞 Поддержка","🔁 /lang"]], resize_keyboard=True)
    elif lang=="uz":
        kb = ReplyKeyboardMarkup([["🛒 Almaz xaridi","🎫 Vaucherlar"],["📞 Support","🔁 /lang"]], resize_keyboard=True)
    else:
        kb = ReplyKeyboardMarkup([["🛒 Купить алмазы","🎫 Ваучеры"],["📞 Поддержка","🔁 /lang"]], resize_keyboard=True)
    try:
        context.bot.send_message(chat_id=uid, text=text, reply_markup=kb)
    except Exception as e:
        logger.exception("menu send err %s", e)

# ---------------- Text handler (menus) ----------------
@anti_spam
def text_handler(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    txt = (update.message.text or "").strip()
    if str(uid) not in users_db:
        return update.message.reply_text("Avval /start bosing")
    lang = get_lang(uid)

    # main menu triggers
    if txt in ["🛒 Хариди алмазҳо","🛒 Almaz xaridi","🛒 Купить алмазы"]:
        send_packages(uid, context); return
    if txt in ["🎫 Ваучерҳо","🎫 Vaucherlar","🎫 Ваучеры"]:
        send_vouchers(uid, context); return
    if txt.startswith("📞") or "Поддержк" in txt or "Support" in txt:
        context.bot.send_message(chat_id=uid, text="📞 Поддержка:\n@Javohir0182"); return
    # package picks by label
    if txt in ["100💎","100 алмаз","100"]: send_package_detail(uid,context,"100"); return
    if txt in ["310💎","310"]: send_package_detail(uid,context,"310"); return
    if txt in ["520💎","520"]: send_package_detail(uid,context,"520"); return
    if txt in ["1060💎","1060"]: send_package_detail(uid,context,"1060"); return
    if txt.lower() in ["1270","прокачка","1270 алмаз"]: send_package_detail(uid,context,"1270"); return
    # voucher picks
    if txt in ["🎫 1 ҳафталик ваучер","1 hafta","1 неделя","1 week"]: send_voucher(uid,context,"week"); return
    if txt in ["🎫 1 моҳлик ваучер","1 oy","1 месяц","1 month"]: send_voucher(uid,context,"month"); return

    # fallback
    context.bot.send_message(chat_id=uid, text={"tj":"Илтимос менюдан танланг.","uz":"Iltimos menyudan tanlang.","ru":"Пожалуйста, выберите опцию."}[lang])

# ---------------- Package & voucher messages ----------------
def send_packages(uid, context: CallbackContext):
    lang = get_lang(uid)
    if lang=="tj":
        txt = ("💰 Нархи алмазҳо:\n\n💠 100💎 — 11 сомонӣ\n💠 310💎 — 31 сомонӣ\n💠 520💎 — 53 сомонӣ\n💠 1060💎 — 103 сомонӣ\n⚡ 1270 (Прокачка) — 43 сомонӣ")
        kb = ReplyKeyboardMarkup([["100💎","310💎"],["520💎","1060💎"],["⚡ Прокачка","🎫 Ваучерҳо"]], resize_keyboard=True)
    elif lang=="uz":
        txt = ("💰 Almaz narxlari:\n\n100💎 — 11 сом\n310💎 — 31 сом\n520💎 — 53 сом\n1060💎 — 103 сом\n1270 — 43 сом")
        kb = ReplyKeyboardMarkup([["100💎","310💎"],["520💎","1060💎"],["⚡ Prokachka","🎫 Vaucherlar"]], resize_keyboard=True)
    else:
        txt = ("💰 Цена алмазов:\n\n100💎 — 11 сом\n310💎 — 31 сом\n520💎 — 53 сом\n1060💎 — 103 сом\n1270 — 43 сом")
        kb = ReplyKeyboardMarkup([["100💎","310💎"],["520💎","1060💎"],["⚡ Прокачка","🎫 Ваучеры"]], resize_keyboard=True)
    context.bot.send_message(chat_id=uid, text=txt, reply_markup=kb)

def send_package_detail(uid, context, code):
    lang = get_lang(uid)
    name = f"{code} алмаз" if code!="1270" else "1270 алмаз (Прокачка)"
    price = PRICES.get(code,0)
    set_last_action(uid, f"buy_{code}")
    if lang=="tj":
        text = f"🔹 {name} — {price} сомонӣ\n💳 Рақами: {PAY_NUMBER}\nПас аз пардохт — скриншот фиристед."
        kb = ReplyKeyboardMarkup([["📤 Скриншот фиристодам","🎫 Ваучер"],["🔙 Бозгашт"]], resize_keyboard=True)
    elif lang=="uz":
        text = f"🔹 {name} — {price} сом\n💳 To'lov: {PAY_NUMBER}\nTo'lovdan keyin skrin yuboring."
        kb = ReplyKeyboardMarkup([["📤 Skreenshot yubordim","🎫 Vaucher"],["🔙 Orqaga"]], resize_keyboard=True)
    else:
        text = f"🔹 {name} — {price} сом\n💳 Номер: {PAY_NUMBER}\nПосле оплаты отправьте скриншот."
        kb = ReplyKeyboardMarkup([["📤 Отправил скриншот","🎫 Ваучер"],["🔙 Назад"]], resize_keyboard=True)
    context.bot.send_message(chat_id=uid, text=text, reply_markup=kb)

def send_vouchers(uid, context: CallbackContext):
    lang = get_lang(uid)
    set_last_action(uid,"vouchers_menu")
    if lang=="tj":
        txt = f"🎫 Ваучерлар:\n1 ҳафта — {VOUCHER_WEEK} сомонӣ\n1 моҳ — {VOUCHER_MONTH} сомонӣ"
        kb = ReplyKeyboardMarkup([["🎫 1 ҳафталик ваучер","🎫 1 моҳлик ваучер"],["🔙 Бозгашт"]], resize_keyboard=True)
    elif lang=="uz":
        txt = f"🎫 Vaucherlar:\n1 hafta — {VOUCHER_WEEK} сом\n1 oy — {VOUCHER_MONTH} сом"
        kb = ReplyKeyboardMarkup([["🎫 1 hafta","🎫 1 oy"],["🔙 Orqaga"]], resize_keyboard=True)
    else:
        txt = f"🎫 Ваучеры:\n1 неделя — {VOUCHER_WEEK} сом\n1 месяц — {VOUCHER_MONTH} сом"
        kb = ReplyKeyboardMarkup([["🎫 1 неделя","🎫 1 месяц"],["🔙 Назад"]], resize_keyboard=True)
    context.bot.send_message(chat_id=uid, text=txt, reply_markup=kb)

def send_voucher(uid, context: CallbackContext, which):
    set_last_action(uid, f"voucher_{which}")
    lang = get_lang(uid)
    price = VOUCHER_WEEK if which=="week" else VOUCHER_MONTH
    if lang=="tj":
        text = f"🎫 Ваучер ({'1 ҳафта' if which=='week' else '1 моҳ'}) — {price} сомонӣ.\nРақам: {PAY_NUMBER}\nПас скрин юборасиз."
        kb = ReplyKeyboardMarkup([["📤 Скриншот фиристодам","🔙 Бозгашт"]], resize_keyboard=True)
    elif lang=="uz":
        text = f"🎫 Voucher — {price} сом\nTo'lov: {PAY_NUMBER}"
        kb = ReplyKeyboardMarkup([["📤 Skreenshot yubordim","🔙 Orqaga"]], resize_keyboard=True)
    else:
        text = f"🎫 Ваучер — {price} сом\nНомер: {PAY_NUMBER}"
        kb = ReplyKeyboardMarkup([["📤 Отправил скриншот","🔙 Назад"]], resize_keyboard=True)
    context.bot.send_message(chat_id=uid, text=text, reply_markup=kb)

# ---------------- Screenshot handler (send to admin + log pending sale) ----------------
@anti_spam
def photo_handler(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    user = update.effective_user
    if not update.message.photo:
        context.bot.send_message(chat_id=uid, text="📸 Илтимос, скриншот расм сифатида юборинг.")
        return
    urec = users_db.get(str(uid), {})
    last = urec.get("last_action","unknown")
    ts = int(time.time())
    human = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S UTC")
    username = f"@{user.username}" if user.username else user.first_name
    caption = f"🆕 Скриншот от {username}\nUser ID: {uid}\nLast action: {last}\nTime: {human}"
    # send to admin
    context.bot.send_message(chat_id=ADMIN_ID, text=caption)
    context.bot.send_photo(chat_id=ADMIN_ID, photo=update.message.photo[-1].file_id)
    # log pending
    sale = {"user_id":uid,"username":user.username or user.first_name,"action":last,"timestamp":ts,"status":"pending"}
    log_sale(sale)
    # reply to user
    context.bot.send_message(chat_id=uid, text="⏳ Скриншот админга юборилди. Тасдиқни кутинг (1-10 дақиқа).")

# ---------------- Admin: /ok* commands ----------------
def admin_ok(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("Сизда бу буйруқни ишлатиш ҳуқуқи йўқ."); return
    parts = update.message.text.strip().split()
    cmd = parts[0].lower()
    target = None
    if len(parts)>=2:
        try: target=int(parts[1])
        except: target=None
    if not target and update.message.reply_to_message and update.message.reply_to_message.text:
        for line in update.message.reply_to_message.text.splitlines():
            if "User ID:" in line:
                try: target=int(line.split("User ID:")[-1].strip().split()[0]); break
                except: target=None
    if not target:
        update.message.reply_text("Илтимос user ID нишонланг. Мисол: /ok100 123456789"); return
    mapping = {"/ok100":"✅ 100 алмаз тасдиқ шуд!","/ok310":"✅ 310 алмаз тасдиқ шуд!","/ok520":"✅ 520 алмаз тасдиқ шуд!","/ok1060":"✅ 1060 алмаз тасдиқ шуд!","/ok1270":"⚡ Прокачка тасдиқ шуд!","/ok_week":"🎫 1 ҳафталик ваучер тасдиқ шуд!","/ok_month":"🎫 1 моҳлик ваучер тасдиқ шуд!"}
    resp = mapping.get(cmd)
    if not resp:
        update.message.reply_text("Номаълум буйруқ. Мисол: /ok100, /ok_week"); return
    try:
        context.bot.send_message(chat_id=target, text=resp)
        # mark pending sale confirmed
        for s in reversed(sales_db):
            if s.get("user_id")==target and s.get("status")=="pending":
                s["status"]="confirmed"
                s["confirmed_by"]=ADMIN_ID
                s["confirmed_at"]=int(time.time())
                s["confirm_msg"]=resp
                break
        write_json(SALES_FILE, sales_db)
        update.message.reply_text(f"Хабар юборилди: {resp}")
    except Exception as e:
        update.message.reply_text(f"Хатолик: {e}")

# ---------------- Admin stats ----------------
def stats_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("Сизда ҳуқуқ йўқ"); return
    income=0; counts={}
    for s in sales_db:
        if s.get("status")=="confirmed":
            a=s.get("action","")
            amt=0
            if a.startswith("buy_"): code=a.split("_",1)[1]; amt=PRICES.get(code,0)
            elif a=="voucher_week": amt=VOUCHER_WEEK
            elif a=="voucher_month": amt=VOUCHER_MONTH
            income+=amt
            counts[a]=counts.get(a,0)+1
    text=f"📊 Total income: {income} сом\nConfirmed records: {len([x for x in sales_db if x.get('status')=='confirmed'])}\n"
    for k,v in counts.items(): text+=f"{k}: {v}\n"
    update.message.reply_text(text)

def users_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("Сизда ҳуқуқ йўқ"); return
    update.message.reply_text(f"👥 Users in DB: {len(users_db)}")

def sales_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("Сизда ҳуқуқ йўқ"); return
    out="🧾 Last sales:\n"
    for s in reversed(sales_db[-20:]): out+=f"{datetime.utcfromtimestamp(s['timestamp']).strftime('%Y-%m-%d %H:%M')} | uid:{s['user_id']} | {s['action']} | {s['status']}\n"
    update.message.reply_text(out)

# ---------------- Setup and run ----------------
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start_cmd))
    dp.add_handler(CallbackQueryHandler(lang_cb, pattern="^lang_"))
    dp.add_handler(CommandHandler("lang", lambda u,c: c.bot.send_message(chat_id=u.effective_user.id, text="Use /start to change language.")))
    dp.add_handler(MessageHandler(Filters.photo, photo_handler))
    dp.add_handler(MessageHandler(Filters.text, text_handler))
    dp.add_handler(CommandHandler(["ok100","ok310","ok520","ok1060","ok1270","ok_week","ok_month"], admin_ok))
    dp.add_handler(CommandHandler("stats", stats_cmd))
    dp.add_handler(CommandHandler("users", users_cmd))
    dp.add_handler(CommandHandler("sales", sales_cmd))

    logger.info("Bot started")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
