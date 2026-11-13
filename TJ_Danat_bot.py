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

# ---- Price list (edit prices here) ----
DIAMONDS = {  # code: (price, label)
    "25": (5, "25💎"),
    "100": (11, "100 + 5💎"),
    "310": (30, "310 + 16💎"),
    "520": (50, "520 + 26💎"),
    "1060": (100, "1060 + 53💎"),
    "2180": (190, "2180 + 218💎"),
    "5600": (465, "5600 + 560💎"),
}
VOUCHERS = {  # key: (price, label, period per language)
    "mini": (7, "90💎", {"tj": "1 ҳафта mini", "uz": "1 hafta mini", "ru": "1 неделя mini"}),
    "week": (16, "450💎", {"tj": "1 ҳафта", "uz": "1 hafta", "ru": "1 неделя"}),
    "month": (110, "2600💎", {"tj": "1 моҳ", "uz": "1 oy", "ru": "1 месяц"}),
}
VOUCHER_BY_NUM = {"90": "mini", "450": "week", "2600": "month"}
BR_CARD_PRICE = 50
EVO = {"3": 10, "7": 13, "30": 36}  # days: price
PAY_NUMBER = os.getenv("PAY_NUMBER", "")

PRICE_BY_ACTION = {}
for _c, (_p, _l) in DIAMONDS.items():
    PRICE_BY_ACTION[f"buy_{_c}"] = _p
for _k, (_p, _l, _per) in VOUCHERS.items():
    PRICE_BY_ACTION[f"voucher_{_k}"] = _p
PRICE_BY_ACTION["brcard"] = BR_CARD_PRICE
for _d, _p in EVO.items():
    PRICE_BY_ACTION[f"evo_{_d}"] = _p

SPAM_INTERVAL = 3  # seconds, used only for /start and photos

# ---------------- Logging ----------------
os.makedirs(DATA_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# ---------------- Storage: Postgres (DATABASE_URL) or local JSON files ----------------
lock = Lock()
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    import psycopg2


def _db_exec(sql, params=(), fetch=False):
    """Run one statement on a fresh connection. Retries because Neon may be waking up."""
    last = None
    for attempt in range(3):
        try:
            conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
            try:
                with conn, conn.cursor() as cur:  # `with conn` commits on success
                    cur.execute(sql, params)
                    return cur.fetchone() if fetch else None
            finally:
                conn.close()
        except Exception as e:
            last = e
            logger.warning("DB attempt %s failed: %s", attempt + 1, e)
            time.sleep(1.5)
    raise last


def init_db():
    if DATABASE_URL:
        _db_exec("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value JSONB NOT NULL)")
        logger.info("Postgres storage ready")
    else:
        logger.warning("DATABASE_URL not set - using local JSON files (data is lost on Render restarts)")


def read_json(path, default):
    with lock:
        if DATABASE_URL:
            key = os.path.basename(path)
            row = _db_exec("SELECT value FROM kv WHERE key = %s", (key,), fetch=True)
            if row is None:
                _db_exec("INSERT INTO kv (key, value) VALUES (%s, %s::jsonb) ON CONFLICT (key) DO NOTHING",
                         (key, json.dumps(default, ensure_ascii=False)))
                return default
            return row[0]
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
        if DATABASE_URL:
            key = os.path.basename(path)
            try:
                _db_exec("INSERT INTO kv (key, value) VALUES (%s, %s::jsonb) "
                         "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                         (key, json.dumps(data, ensure_ascii=False)))
            except Exception:
                logger.exception("DB write failed for %s (data kept in memory only)", key)
            return
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


init_db()
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
    "ask_id": {"tj": "🎮 Free Fire ID-и худро (танҳо рақамҳо) нависед:",
               "uz": "🎮 Free Fire ID raqamingizni (faqat raqamlar) yozing:",
               "ru": "🎮 Введите ваш Free Fire ID (только цифры):"},
    "bad_id": {"tj": "❌ ID нодуруст аст. Танҳо рақамҳо нависед (6–14 рақам) ё 🔙 пахш кунед.",
               "uz": "❌ ID noto'g'ri. Faqat raqam yozing (6–14 ta) yoki 🔙 bosing.",
               "ru": "❌ Неверный ID. Введите только цифры (6–14) или нажмите 🔙."},
    "ask_nick": {"tj": "👤 Акнун Free Fire никнейми худро дар бозӣ чӣ тавр бошад, айнан нависед:",
                 "uz": "👤 Endi Free Fire nikneymingizni o'yindagidek aynan yozing:",
                 "ru": "👤 Теперь напишите ваш ник в Free Fire точно так, как в игре:"},
    "bad_nick": {"tj": "❌ Никнейм 1–40 аломат бошад.", "uz": "❌ Nikneym 1–40 belgi bo'lsin.",
                 "ru": "❌ Ник должен быть от 1 до 40 символов."},
    "confirm_q": {"tj": "🔎 Лутфан бори дигар санҷед:\n\n🆔 ID: {id}\n👤 Никнейм: {nick}\n\nДуруст аст?",
                  "uz": "🔎 Iltimos, yana bir bor tekshiring:\n\n🆔 ID: {id}\n👤 Nikneym: {nick}\n\nTo'g'rimi?",
                  "ru": "🔎 Пожалуйста, проверьте ещё раз:\n\n🆔 ID: {id}\n👤 Ник: {nick}\n\nВсё верно?"},
    "need_buttons": {"tj": "Тугмаро пахш кунед: ✅ ё ✏️", "uz": "Tugmani bosing: ✅ yoki ✏️",
                     "ru": "Нажмите кнопку: ✅ или ✏️"},
    "need_order": {"tj": "Аввал маҳсулот интихоб кунед, ID ва никро тасдиқ намоед, баъд скриншот фиристед.",
                   "uz": "Avval mahsulotni tanlang, ID va nikni tasdiqlang, keyin skrinshot yuboring.",
                   "ru": "Сначала выберите товар и подтвердите ID и ник, затем отправьте скриншот."},
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
        kb = ReplyKeyboardMarkup([["🛒 Хариди алмазҳо", "🎫 Ваучерҳо"], ["🌟 BR Card", "🦾 EVO рӯзона"], ["📞 Поддержка", "🔁 /lang"]], resize_keyboard=True)
    elif lang == "uz":
        kb = ReplyKeyboardMarkup([["🛒 Almaz xaridi", "🎫 Vaucherlar"], ["🌟 BR Card", "🦾 EVO kunlik"], ["📞 Support", "🔁 /lang"]], resize_keyboard=True)
    else:
        kb = ReplyKeyboardMarkup([["🛒 Купить алмазы", "🎫 Ваучеры"], ["🌟 BR Card", "🦾 EVO на дни"], ["📞 Поддержка", "🔁 /lang"]], resize_keyboard=True)
    try:
        context.bot.send_message(chat_id=uid, text=text, reply_markup=kb)
    except Exception as e:
        logger.exception("menu send err %s", e)


# ---------------- Text handler ----------------
PKG_RE = re.compile(r"^(25|100|310|520|1060|2180|5600)\s*(💎|алмаз|almaz)?$", re.I)

L_VOUCH = {"tj": "🎫 Ваучерҳо", "uz": "🎫 Vaucherlar", "ru": "🎫 Ваучеры"}
L_BACK = {"tj": "🔙 Бозгашт", "uz": "🔙 Orqaga", "ru": "🔙 Назад"}
L_SHOT = {"tj": "📤 Скриншот фиристодам", "uz": "📤 Skreenshot yubordim", "ru": "📤 Отправил скриншот"}
BTN_ESKHATA = "🏦 Eskhata"
BTN_DCITY = "💳 DCity"
CARD_NAMES = {"eskhata": "Eskhata Bank", "dcity": "DCity"}
L_YES = {"tj": "✅ Ҳа, дуруст аст", "uz": "✅ Ha, to'g'ri", "ru": "✅ Да, верно"}
L_NO = {"tj": "✏️ Не, ислоҳ мекунам", "uz": "✏️ Yo'q, tuzataman", "ru": "✏️ Нет, исправить"}
MENU_LABELS = {"🛒 Хариди алмазҳо", "🎫 Ваучерҳо", "🌟 BR Card", "🦾 EVO рӯзона", "📞 Поддержка",
               "🛒 Almaz xaridi", "🎫 Vaucherlar", "🦾 EVO kunlik", "📞 Support",
               "🛒 Купить алмазы", "🎫 Ваучеры", "🦾 EVO на дни"}
ORDER_PREFIXES = ("buy_", "voucher_", "brcard", "evo_")
CUR = {"tj": "сомонӣ", "uz": "сом", "ru": "сом"}
EVO_DAYS = {"tj": "рӯз", "uz": "kun", "ru": "дн."}


def text_handler(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    txt = (update.message.text or "").strip()
    low = txt.lower()

    if str(uid) not in users_db or "lang" not in users_db[str(uid)]:
        update.message.reply_text(tx("need_start", "ru") + " / Avval /start bosing")
        return
    lang = get_lang(uid)

    # order flow (Free Fire ID / nickname / confirmation)
    rec = users_db[str(uid)]
    if "🔙" in txt or txt in MENU_LABELS or txt.startswith("🔁"):
        rec["state"] = None  # leaving the order flow
    if rec.get("state") and handle_order_flow(uid, context, txt, rec, lang):
        return

    # back / language
    if "🔙" in txt:
        send_main_menu(uid, context)
        return
    if txt.startswith("🔁"):
        lang_cmd(update, context)
        return

    # card choice
    if "eskhata" in low or "эсхата" in low or "dcity" in low:
        rec = users_db.get(str(uid), {})
        if not str(rec.get("last_action", "")).startswith(ORDER_PREFIXES) or not rec.get("ff_id"):
            send_main_menu(uid, context)
            return
        key = "dcity" if "dcity" in low else "eskhata"
        rec["card"] = key
        write_json(USERS_FILE, users_db)
        msg = {"tj": "✅ Корт интихоб шуд: {c}\nПас аз пардохт скриншот фиристед.",
               "uz": "✅ Karta tanlandi: {c}\nTo'lovdan keyin skrin yuboring.",
               "ru": "✅ Карта выбрана: {c}\nПосле оплаты отправьте скриншот."}[lang]
        context.bot.send_message(chat_id=uid, text=msg.format(c=CARD_NAMES[key]))
        return

    # screenshot button -> ask for a photo
    if txt.startswith("📤"):
        context.bot.send_message(chat_id=uid, text=tx("send_photo", lang))
        return

    # support
    if txt.startswith("📞") or "поддержк" in low or "support" in low:
        context.bot.send_message(chat_id=uid, text=f"📞 Поддержка:\n{SUPPORT_USERNAME}")
        return

    # vouchers: "🎫 90💎" / "🎫 450💎" / "🎫 2600💎" or the menu button
    if "🎫" in txt:
        m = re.search(r"\d+", txt)
        if m and m.group(0) in VOUCHER_BY_NUM:
            send_voucher(uid, context, VOUCHER_BY_NUM[m.group(0)])
        else:
            send_vouchers(uid, context)
        return

    # EVO: "🦾 3 рӯз" or the menu button
    if "🦾" in txt:
        m = re.search(r"\d+", txt)
        if m and m.group(0) in EVO:
            send_evo(uid, context, m.group(0))
        else:
            send_evo_menu(uid, context)
        return

    # BR Card
    if txt.startswith("🌟") or "br card" in low:
        send_item(uid, context, "brcard", "🌟 BR Card", BR_CARD_PRICE)
        return

    # buy menu
    if txt.startswith("🛒"):
        send_packages(uid, context)
        return

    # diamond packages
    m = PKG_RE.match(txt)
    if m:
        send_package_detail(uid, context, m.group(1))
        return

    context.bot.send_message(chat_id=uid, text=tx("fallback", lang))


# ---------------- Menus & item messages ----------------
def send_packages(uid, context: CallbackContext):
    lang = get_lang(uid)
    set_last_action(uid, "packages_menu")
    head = {"tj": "💰 Нархи алмазҳо:", "uz": "💰 Almaz narxlari:", "ru": "💰 Цена алмазов:"}[lang]
    lines = "\n".join(f"💠 {label} — {price} {CUR[lang]}" for price, label in DIAMONDS.values())
    kb = ReplyKeyboardMarkup([["25💎", "100💎"], ["310💎", "520💎"], ["1060💎", "2180💎"],
                              ["5600💎", L_VOUCH[lang]], [L_BACK[lang]]], resize_keyboard=True)
    context.bot.send_message(chat_id=uid, text=f"{head}\n\n{lines}", reply_markup=kb)


def send_item(uid, context, action, title, price):
    """Start an order: first ask for the Free Fire ID."""
    lang = get_lang(uid)
    rec = users_db.setdefault(str(uid), {})
    rec.update({"card": None, "ff_id": None, "ff_nick": None, "state": "await_id",
                "pending": [action, title, price]})
    set_last_action(uid, action)  # also saves users.json
    context.bot.send_message(chat_id=uid, text=tx("ask_id", lang),
                             reply_markup=ReplyKeyboardMarkup([[L_BACK[lang]]], resize_keyboard=True))


def handle_order_flow(uid, context, txt, rec, lang):
    """ID -> nickname -> confirmation. Returns True if the message was consumed."""
    state = rec.get("state")
    back_kb = ReplyKeyboardMarkup([[L_BACK[lang]]], resize_keyboard=True)
    if state == "await_id":
        digits = txt.replace(" ", "")
        if re.fullmatch(r"\d{6,14}", digits):
            rec["ff_id"] = digits
            rec["state"] = "await_nick"
            write_json(USERS_FILE, users_db)
            context.bot.send_message(chat_id=uid, text=tx("ask_nick", lang), reply_markup=back_kb)
        else:
            context.bot.send_message(chat_id=uid, text=tx("bad_id", lang), reply_markup=back_kb)
        return True
    if state == "await_nick":
        nick = txt.strip()
        if 1 <= len(nick) <= 40:
            rec["ff_nick"] = nick
            rec["state"] = "await_confirm"
            write_json(USERS_FILE, users_db)
            kb = ReplyKeyboardMarkup([[L_YES[lang]], [L_NO[lang]], [L_BACK[lang]]], resize_keyboard=True)
            context.bot.send_message(chat_id=uid, reply_markup=kb,
                                     text=tx("confirm_q", lang).format(id=rec["ff_id"], nick=nick))
        else:
            context.bot.send_message(chat_id=uid, text=tx("bad_nick", lang), reply_markup=back_kb)
        return True
    if state == "await_confirm":
        if txt.startswith("✅"):
            rec["state"] = None
            write_json(USERS_FILE, users_db)
            action, title, price = rec["pending"]
            show_payment(uid, context, action, title, price)
        elif txt.startswith("✏️"):
            rec.update({"ff_id": None, "ff_nick": None, "state": "await_id"})
            write_json(USERS_FILE, users_db)
            context.bot.send_message(chat_id=uid, text=tx("ask_id", lang), reply_markup=back_kb)
        else:
            context.bot.send_message(chat_id=uid, text=tx("need_buttons", lang))
        return True
    return False


def show_payment(uid, context, action, title, price):
    """Payment instructions (shown after the ID and nickname are confirmed)."""
    lang = get_lang(uid)
    cur = CUR[lang]
    if lang == "tj":
        text = f"🔹 {title} — {price} {cur}\n💳 Рақам: {PAY_NUMBER}\nКортро интихоб кунед, пас аз пардохт скриншот фиристед."
    elif lang == "uz":
        text = f"🔹 {title} — {price} {cur}\n💳 To'lov: {PAY_NUMBER}\nKartani tanlang, to'lovdan keyin skrin yuboring."
    else:
        text = f"🔹 {title} — {price} {cur}\n💳 Номер: {PAY_NUMBER}\nВыберите карту, после оплаты отправьте скриншот."
    kb = ReplyKeyboardMarkup([[BTN_ESKHATA, BTN_DCITY], [L_SHOT[lang]], [L_BACK[lang]]], resize_keyboard=True)
    context.bot.send_message(chat_id=uid, text=text, reply_markup=kb)


def send_package_detail(uid, context, code):
    price, label = DIAMONDS[code]
    send_item(uid, context, f"buy_{code}", f"💎 {label}", price)


def send_vouchers(uid, context: CallbackContext):
    lang = get_lang(uid)
    set_last_action(uid, "vouchers_menu")
    head = {"tj": "🎫 Ваучерҳо:", "uz": "🎫 Vaucherlar:", "ru": "🎫 Ваучеры:"}[lang]
    lines = "\n".join(f"{label} ({per[lang]}) — {price} {CUR[lang]}" for price, label, per in VOUCHERS.values())
    kb = ReplyKeyboardMarkup([["🎫 90💎", "🎫 450💎"], ["🎫 2600💎"], [L_BACK[lang]]], resize_keyboard=True)
    context.bot.send_message(chat_id=uid, text=f"{head}\n{lines}", reply_markup=kb)


def send_voucher(uid, context: CallbackContext, which):
    lang = get_lang(uid)
    price, label, per = VOUCHERS[which]
    send_item(uid, context, f"voucher_{which}", f"🎫 {label} ({per[lang]})", price)


def send_evo_menu(uid, context: CallbackContext):
    lang = get_lang(uid)
    set_last_action(uid, "evo_menu")
    head = {"tj": "🦾 EVO рӯзона:", "uz": "🦾 EVO kunlik:", "ru": "🦾 EVO на дни:"}[lang]
    lines = "\n".join(f"{d} {EVO_DAYS[lang]} — {p} {CUR[lang]}" for d, p in EVO.items())
    kb = ReplyKeyboardMarkup([[f"🦾 3 {EVO_DAYS[lang]}", f"🦾 7 {EVO_DAYS[lang]}"],
                              [f"🦾 30 {EVO_DAYS[lang]}"], [L_BACK[lang]]], resize_keyboard=True)
    context.bot.send_message(chat_id=uid, text=f"{head}\n{lines}", reply_markup=kb)


def send_evo(uid, context: CallbackContext, days):
    lang = get_lang(uid)
    send_item(uid, context, f"evo_{days}", f"🦾 EVO — {days} {EVO_DAYS[lang]}", EVO[days])


# ---------------- Screenshot handler ----------------
@anti_spam
def photo_handler(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    user = update.effective_user
    lang = get_lang(uid)
    last = users_db.get(str(uid), {}).get("last_action", "unknown")
    rec = users_db.get(str(uid), {})
    if rec.get("state") or not rec.get("ff_id") or not str(last).startswith(ORDER_PREFIXES):
        context.bot.send_message(chat_id=uid, text=tx("need_order", lang))
        return
    ts = int(time.time())
    username = f"@{user.username}" if user.username else user.first_name
    card = CARD_NAMES.get(users_db.get(str(uid), {}).get("card"), "не выбрана")
    caption = (f"🆕 Скриншот от {username}\nUser ID: {uid}\n"
               f"Last action: {last}\n🎮 FF ID: {rec.get('ff_id')}\n👤 Ник: {rec.get('ff_nick')}\n"
               f"💳 Карта: {card}\nTime: {utc_str(ts)}")
    try:
        context.bot.send_photo(chat_id=ADMIN_ID, photo=update.message.photo[-1].file_id, caption=caption)
    except Exception as e:
        logger.exception("send to admin failed: %s", e)
    log_sale({"user_id": uid, "username": user.username or user.first_name,
              "action": last, "card": card, "ff_id": rec.get("ff_id"), "ff_nick": rec.get("ff_nick"),
              "timestamp": ts, "status": "pending"})
    context.bot.send_message(chat_id=uid, text=tx("photo_sent", lang))


# ---------------- Admin: /ok* ----------------
OK_MAP = {}
for _c, (_p, _l) in DIAMONDS.items():
    OK_MAP[f"/ok{_c}"] = (f"buy_{_c}", f"✅ {_l} тасдиқ шуд!")
for _k, (_p, _l, _per) in VOUCHERS.items():
    OK_MAP[f"/ok_{_k}"] = (f"voucher_{_k}", f"🎫 {_l} ваучер тасдиқ шуд!")
OK_MAP["/ok_brcard"] = ("brcard", "🌟 BR Card тасдиқ шуд!")
for _d in EVO:
    OK_MAP[f"/ok_evo{_d}"] = (f"evo_{_d}", f"🦾 EVO {_d} рӯз тасдиқ шуд!")


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
    return PRICE_BY_ACTION.get(a, 0)


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
        out += f"{utc_str(s['timestamp'], '%Y-%m-%d %H:%M')} | uid:{s['user_id']} | {s['action']} | {s.get('card', '-')} | {s['status']}\n"
    update.message.reply_text(out)


# ---------------- Keep-alive web server (for Render web service) ----------------
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer


class _PingHandler(BaseHTTPRequestHandler):
    def _ok(self, body=True):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        if body:
            self.wfile.write(b"Bot is running")

    def do_GET(self):
        self._ok()

    def do_HEAD(self):  # UptimeRobot often uses HEAD
        self._ok(body=False)

    def log_message(self, *args):
        pass


def start_web_server():
    port = os.getenv("PORT")  # Render sets this automatically
    if not port:
        return
    server = HTTPServer(("0.0.0.0", int(port)), _PingHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    logger.info("Web server listening on port %s", port)


# ---------------- Run ----------------
def main():
    start_web_server()
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
