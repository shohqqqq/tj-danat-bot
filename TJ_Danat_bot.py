# -*- coding: utf-8 -*-
# TJ_Danat_bot.py — fixed version
# Requires: python-telegram-bot==13.15 (Python 3.8–3.12)
# Run:  export BOT_TOKEN="your_new_token"   (Windows: set BOT_TOKEN=...)

import os
import re
import time
import json
import logging
from datetime import datetime, timezone
from functools import wraps
from threading import Lock

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters,
                          CallbackQueryHandler, CallbackContext)

# ---------------- CONFIG ----------------
try:
    from dotenv import load_dotenv
    load_dotenv()  # reads .env if present
except ImportError:
    pass

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN (env variable or .env file) before running the bot.")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
if not ADMIN_ID:
    raise RuntimeError("Set ADMIN_ID (your Telegram numeric user ID).")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@support")
DATA_DIR = "data"
USERS_FILE = os.path.join(DATA_DIR, "users.json")
SALES_FILE = os.path.join(DATA_DIR, "sales.json")
LOG_FILE = os.path.join(DATA_DIR, "bot.log")

PRICES = {"100": 11, "310": 31, "520": 53, "1060": 103, "1270": 43}
VOUCHER_WEEK = 18
VOUCHER_MONTH = 115
PAY_NUMBER = os.getenv("PAY_NUMBER", "")
SPAM_INTERVAL = 3  # seconds, used only for /start and photos

# ---------------- Logging ----------------
os.makedirs(DATA_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
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
            except Exception:
                return default


def write_json(path, data):
    with lock:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


users_db = read_json(USERS_FILE, {})
sales_db = read_json(SALES_FILE, [])

# ---------------- Anti-spam ----------------
last_ts = {}


def anti_spam(func):
    @wraps(func)
    def wrapper(update: Update, context: CallbackContext, *a, **kw):
        uid = update.effective_user.id if update.effective_user else None
        if uid:
            now = time.time()
            if now - last_ts.get(uid, 0) < SPAM_INTERVAL:
                try:
                    update.message.reply_text("⏳ Илтимос, бир неча сониядан кейин қайта уриниб кўринг.")
                except Exception:
                    pass
                return
            last_ts[uid] = now
        return func(update, context, *a, **kw)
    return wrapper


# ---------------- Texts ----------------
TEXTS = {
    "start": {"tj": "💎 Салом! Лутфан забонро интихоб кунед:",
              "uz": "💎 Salom! Iltimos tilni tanlang:",
              "ru": "💎 Привет! Выберите язык:"},
    "welcome": {"tj": "✅ Забон интихоб шуд. Лутфан танланг:",
                "uz": "✅ Til tanlandi. Iltimos tanlang:",
                "ru": "✅ Язык выбран. Пожалуйста, выберите:"},
    "menu": {"tj": "Лутфан танланг:", "uz": "Iltimos tanlang:", "ru": "Пожалуйста, выберите:"},
    "fallback": {"tj": "Илтимос менюдан танланг.", "uz": "Iltimos menyudan tanlang.",
                 "ru": "Пожалуйста, выберите опцию."},
    "send_photo": {"tj": "📸 Скриншотро ҳамчун расм фиристед.",
                   "uz": "📸 Skrinshotni rasm sifatida yuboring.",
                   "ru": "📸 Отправьте скриншот как фото."},
    "photo_sent": {"tj": "⏳ Скриншот ба админ фиристода шуд. Тасдиқро интизор шавед (1-10 дақиқа).",
                   "uz": "⏳ Skrinshot adminga yuborildi. Tasdiqni kuting (1-10 daqiqa).",
                   "ru": "⏳ Скриншот отправлен админу. Ожидайте подтверждения (1-10 минут)."},
    "need_start": {"tj": "Аввал /start пахш кунед", "uz": "Avval /start bosing", "ru": "Сначала нажмите /start"},
}


def tx(key, lang):
    d = TEXTS.get(key, {})
    return d.get(lang, d.get("ru", ""))


# ---------------- Helpers ----------------
def get_lang(uid):
    return users_db.get(str(uid), {}).get("lang", "tj")


def set_lang(uid, lang):
    users_db.setdefault(str(uid), {})["lang"] = lang
    write_json(USERS_FILE, users_db)


def set_last_action(uid, action):
    rec = users_db.setdefault(str(uid), {})
    rec["last_action"] = action
    rec["last_time"] = int(time.time())
    write_json(USERS_FILE, users_db)


def log_sale(rec):
    sales_db.append(rec)
    write_json(SALES_FILE, sales_db)


def utc_str(ts, fmt="%Y-%m-%d %H:%M:%S UTC"):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(fmt)


# ---------------- Start & language ----------------
def lang_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Тоҷикӣ 🇹🇯", callback_data="lang_tj"),
         InlineKeyboardButton("O‘zbek 🇺🇿", callback_data="lang_uz")],
        [InlineKeyboardButton("Русский 🇷🇺", callback_data="lang_ru")],
    ])


@anti_spam
def start_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(
        "💎 Салом! / Salom! / Привет!\nЗабонро интихоб кунед / Tilni tanlang / Выберите язык:",
        reply_markup=lang_kb())


def lang_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Забонро интихоб кунед / Tilni tanlang / Выберите язык:", reply_markup=lang_kb())


def lang_cb(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    lang = q.data.split("_")[-1]
    if lang not in ("tj", "uz", "ru"):
        lang = "tj"
    set_lang(q.from_user.id, lang)
    send_main_menu(q.from_user.id, context, welcome=True)


def send_main_menu(uid, context: CallbackContext, welcome=False):
    lang = get_lang(uid)
    text = tx("welcome", lang) if welcome else tx("menu", lang)
    if lang == "tj":
        kb = ReplyKeyboardMarkup([["🛒 Хариди алмазҳо", "🎫 Ваучерҳо"], ["📞 Поддержка", "🔁 /lang"]], resize_keyboard=True)
    elif lang == "uz":
        kb = ReplyKeyboardMarkup([["🛒 Almaz xaridi", "🎫 Vaucherlar"], ["📞 Support", "🔁 /lang"]], resize_keyboard=True)
    else:
        kb = ReplyKeyboardMarkup([["🛒 Купить алмазы", "🎫 Ваучеры"], ["📞 Поддержка", "🔁 /lang"]], resize_keyboard=True)
    try:
        context.bot.send_message(chat_id=uid, text=text, reply_markup=kb)
    except Exception as e:
        logger.exception("menu send err %s", e)


# ---------------- Text handler ----------------
PKG_RE = re.compile(r"^(100|310|520|1060)\s*(💎|алмаз|almaz)?$", re.I)
WEEK_WORDS = ("ҳафта", "hafta", "недел", "week")
MONTH_WORDS = ("моҳ", "oy", "месяц", "month")


def text_handler(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    txt = (update.message.text or "").strip()
    low = txt.lower()

    if str(uid) not in users_db or "lang" not in users_db[str(uid)]:
        update.message.reply_text(tx("need_start", "ru") + " / Avval /start bosing")
        return
    lang = get_lang(uid)

    # back / language
    if "🔙" in txt:
        send_main_menu(uid, context)
        return
    if txt.startswith("🔁"):
        lang_cmd(update, context)
        return

    # screenshot button -> ask for a photo
    if txt.startswith("📤"):
        context.bot.send_message(chat_id=uid, text=tx("send_photo", lang))
        return

    # support
    if txt.startswith("📞") or "поддержк" in low or "support" in low:
        context.bot.send_message(chat_id=uid, text=f"📞 Поддержка:\n{SUPPORT_USERNAME}")
        return

    # vouchers (check week/month before the generic voucher menu)
    is_voucher_ctx = "🎫" in txt or low in ("1 hafta", "1 oy", "1 неделя", "1 месяц", "1 week", "1 month")
    if is_voucher_ctx:
        if any(w in low for w in WEEK_WORDS):
            send_voucher(uid, context, "week")
        elif re.search(r"(?<!\w)oy(?!\w)", low) or any(w in low for w in MONTH_WORDS):
            send_voucher(uid, context, "month")
        else:
            send_vouchers(uid, context)
        return

    # buy menu
    if txt.startswith("🛒"):
        send_packages(uid, context)
        return

    # packages
    m = PKG_RE.match(txt)
    if m:
        send_package_detail(uid, context, m.group(1))
        return
    if "прокачка" in low or "prokachka" in low or low.startswith("1270") or txt.startswith("⚡"):
        send_package_detail(uid, context, "1270")
        return

    context.bot.send_message(chat_id=uid, text=tx("fallback", lang))


# ---------------- Package & voucher messages ----------------
def send_packages(uid, context: CallbackContext):
    lang = get_lang(uid)
    set_last_action(uid, "packages_menu")
    if lang == "tj":
        txt = ("💰 Нархи алмазҳо:\n\n💠 100💎 — 11 сомонӣ\n💠 310💎 — 31 сомонӣ\n💠 520💎 — 53 сомонӣ\n"
               "💠 1060💎 — 103 сомонӣ\n⚡ 1270 (Прокачка) — 43 сомонӣ")
        kb = ReplyKeyboardMarkup([["100💎", "310💎"], ["520💎", "1060💎"], ["⚡ Прокачка", "🎫 Ваучерҳо"], ["🔙 Бозгашт"]], resize_keyboard=True)
    elif lang == "uz":
        txt = "💰 Almaz narxlari:\n\n100💎 — 11 сом\n310💎 — 31 сом\n520💎 — 53 сом\n1060💎 — 103 сом\n1270 — 43 сом"
        kb = ReplyKeyboardMarkup([["100💎", "310💎"], ["520💎", "1060💎"], ["⚡ Prokachka", "🎫 Vaucherlar"], ["🔙 Orqaga"]], resize_keyboard=True)
    else:
        txt = "💰 Цена алмазов:\n\n100💎 — 11 сом\n310💎 — 31 сом\n520💎 — 53 сом\n1060💎 — 103 сом\n1270 — 43 сом"
        kb = ReplyKeyboardMarkup([["100💎", "310💎"], ["520💎", "1060💎"], ["⚡ Прокачка", "🎫 Ваучеры"], ["🔙 Назад"]], resize_keyboard=True)
    context.bot.send_message(chat_id=uid, text=txt, reply_markup=kb)


def send_package_detail(uid, context, code):
    lang = get_lang(uid)
    name = f"{code} алмаз" if code != "1270" else "1270 алмаз (Прокачка)"
    price = PRICES.get(code, 0)
    set_last_action(uid, f"buy_{code}")
    if lang == "tj":
        text = f"🔹 {name} — {price} сомонӣ\n💳 Рақам: {PAY_NUMBER}\nПас аз пардохт — скриншот фиристед."
        kb = ReplyKeyboardMarkup([["📤 Скриншот фиристодам", "🎫 Ваучерҳо"], ["🔙 Бозгашт"]], resize_keyboard=True)
    elif lang == "uz":
        text = f"🔹 {name} — {price} сом\n💳 To'lov: {PAY_NUMBER}\nTo'lovdan keyin skrin yuboring."
        kb = ReplyKeyboardMarkup([["📤 Skreenshot yubordim", "🎫 Vaucherlar"], ["🔙 Orqaga"]], resize_keyboard=True)
    else:
        text = f"🔹 {name} — {price} сом\n💳 Номер: {PAY_NUMBER}\nПосле оплаты отправьте скриншот."
        kb = ReplyKeyboardMarkup([["📤 Отправил скриншот", "🎫 Ваучеры"], ["🔙 Назад"]], resize_keyboard=True)
    context.bot.send_message(chat_id=uid, text=text, reply_markup=kb)


def send_vouchers(uid, context: CallbackContext):
    lang = get_lang(uid)
    set_last_action(uid, "vouchers_menu")
    if lang == "tj":
        txt = f"🎫 Ваучерҳо:\n1 ҳафта — {VOUCHER_WEEK} сомонӣ\n1 моҳ — {VOUCHER_MONTH} сомонӣ"
        kb = ReplyKeyboardMarkup([["🎫 1 ҳафталик ваучер", "🎫 1 моҳлик ваучер"], ["🔙 Бозгашт"]], resize_keyboard=True)
    elif lang == "uz":
        txt = f"🎫 Vaucherlar:\n1 hafta — {VOUCHER_WEEK} сом\n1 oy — {VOUCHER_MONTH} сом"
        kb = ReplyKeyboardMarkup([["🎫 1 hafta", "🎫 1 oy"], ["🔙 Orqaga"]], resize_keyboard=True)
    else:
        txt = f"🎫 Ваучеры:\n1 неделя — {VOUCHER_WEEK} сом\n1 месяц — {VOUCHER_MONTH} сом"
        kb = ReplyKeyboardMarkup([["🎫 1 неделя", "🎫 1 месяц"], ["🔙 Назад"]], resize_keyboard=True)
    context.bot.send_message(chat_id=uid, text=txt, reply_markup=kb)


def send_voucher(uid, context: CallbackContext, which):
    set_last_action(uid, f"voucher_{which}")
    lang = get_lang(uid)
    price = VOUCHER_WEEK if which == "week" else VOUCHER_MONTH
    if lang == "tj":
        period = "1 ҳафта" if which == "week" else "1 моҳ"
        text = f"🎫 Ваучер ({period}) — {price} сомонӣ\n💳 Рақам: {PAY_NUMBER}\nПас аз пардохт скриншот фиристед."
        kb = ReplyKeyboardMarkup([["📤 Скриншот фиристодам", "🔙 Бозгашт"]], resize_keyboard=True)
    elif lang == "uz":
        period = "1 hafta" if which == "week" else "1 oy"
        text = f"🎫 Vaucher ({period}) — {price} сом\n💳 To'lov: {PAY_NUMBER}\nTo'lovdan keyin skrin yuboring."
        kb = ReplyKeyboardMarkup([["📤 Skreenshot yubordim", "🔙 Orqaga"]], resize_keyboard=True)
    else:
        period = "1 неделя" if which == "week" else "1 месяц"
        text = f"🎫 Ваучер ({period}) — {price} сом\n💳 Номер: {PAY_NUMBER}\nПосле оплаты отправьте скриншот."
        kb = ReplyKeyboardMarkup([["📤 Отправил скриншот", "🔙 Назад"]], resize_keyboard=True)
    context.bot.send_message(chat_id=uid, text=text, reply_markup=kb)


# ---------------- Screenshot handler ----------------
@anti_spam
def photo_handler(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    user = update.effective_user
    lang = get_lang(uid)
    last = users_db.get(str(uid), {}).get("last_action", "unknown")
    ts = int(time.time())
    username = f"@{user.username}" if user.username else user.first_name
    caption = (f"🆕 Скриншот от {username}\nUser ID: {uid}\n"
               f"Last action: {last}\nTime: {utc_str(ts)}")
    try:
        context.bot.send_photo(chat_id=ADMIN_ID, photo=update.message.photo[-1].file_id, caption=caption)
    except Exception as e:
        logger.exception("send to admin failed: %s", e)
    log_sale({"user_id": uid, "username": user.username or user.first_name,
              "action": last, "timestamp": ts, "status": "pending"})
    context.bot.send_message(chat_id=uid, text=tx("photo_sent", lang))


# ---------------- Admin: /ok* ----------------
OK_MAP = {
    "/ok100": ("buy_100", "✅ 100 алмаз тасдиқ шуд!"),
    "/ok310": ("buy_310", "✅ 310 алмаз тасдиқ шуд!"),
    "/ok520": ("buy_520", "✅ 520 алмаз тасдиқ шуд!"),
    "/ok1060": ("buy_1060", "✅ 1060 алмаз тасдиқ шуд!"),
    "/ok1270": ("buy_1270", "⚡ Прокачка тасдиқ шуд!"),
    "/ok_week": ("voucher_week", "🎫 1 ҳафталик ваучер тасдиқ шуд!"),
    "/ok_month": ("voucher_month", "🎫 1 моҳлик ваучер тасдиқ шуд!"),
}


def admin_ok(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("Сизда бу буйруқни ишлатиш ҳуқуқи йўқ.")
        return
    parts = update.message.text.strip().split()
    cmd = parts[0].split("@")[0].lower()
    target = None
    if len(parts) >= 2:
        try:
            target = int(parts[1])
        except ValueError:
            target = None
    if not target and update.message.reply_to_message:
        r = update.message.reply_to_message
        src = r.text or r.caption or ""
        for line in src.splitlines():
            if "User ID:" in line:
                try:
                    target = int(line.split("User ID:")[-1].strip().split()[0])
                    break
                except Exception:
                    target = None
    if not target:
        update.message.reply_text("Илтимос user ID нишон диҳед. Мисол: /ok100 123456789")
        return
    if cmd not in OK_MAP:
        update.message.reply_text("Номаълум буйруқ. Мисол: /ok100, /ok_week")
        return
    action, resp = OK_MAP[cmd]
    try:
        context.bot.send_message(chat_id=target, text=resp)
        for s in reversed(sales_db):
            if s.get("user_id") == target and s.get("status") == "pending":
                s["status"] = "confirmed"
                s["action"] = action  # what admin actually confirmed
                s["confirmed_by"] = ADMIN_ID
                s["confirmed_at"] = int(time.time())
                s["confirm_msg"] = resp
                break
        write_json(SALES_FILE, sales_db)
        update.message.reply_text(f"Хабар юборилди: {resp}")
    except Exception as e:
        update.message.reply_text(f"Хатолик: {e}")


# ---------------- Admin stats ----------------
def action_amount(a):
    if a.startswith("buy_"):
        return PRICES.get(a.split("_", 1)[1], 0)
    if a == "voucher_week":
        return VOUCHER_WEEK
    if a == "voucher_month":
        return VOUCHER_MONTH
    return 0


def stats_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("Сизда ҳуқуқ йўқ")
        return
    income = 0
    counts = {}
    confirmed = [s for s in sales_db if s.get("status") == "confirmed"]
    for s in confirmed:
        a = s.get("action", "")
        income += action_amount(a)
        counts[a] = counts.get(a, 0) + 1
    text = f"📊 Total income: {income} сом\nConfirmed records: {len(confirmed)}\n"
    for k, v in counts.items():
        text += f"{k}: {v}\n"
    update.message.reply_text(text)


def users_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("Сизда ҳуқуқ йўқ")
        return
    update.message.reply_text(f"👥 Users in DB: {len(users_db)}")


def sales_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("Сизда ҳуқуқ йўқ")
        return
    out = "🧾 Last sales:\n"
    for s in reversed(sales_db[-20:]):
        out += f"{utc_str(s['timestamp'], '%Y-%m-%d %H:%M')} | uid:{s['user_id']} | {s['action']} | {s['status']}\n"
    update.message.reply_text(out)


# ---------------- Run ----------------
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start_cmd))
    dp.add_handler(CommandHandler("lang", lang_cmd))
    dp.add_handler(CallbackQueryHandler(lang_cb, pattern="^lang_"))
    dp.add_handler(CommandHandler(list(c.lstrip("/") for c in OK_MAP), admin_ok))
    dp.add_handler(CommandHandler("stats", stats_cmd))
    dp.add_handler(CommandHandler("users", users_cmd))
    dp.add_handler(CommandHandler("sales", sales_cmd))
    dp.add_handler(MessageHandler(Filters.photo, photo_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, text_handler))

    logger.info("Bot started")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
