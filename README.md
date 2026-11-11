# TJ Danat Bot

Telegram bot for selling in-game diamonds and vouchers (Tajik / Uzbek / Russian).
Users pick a package, pay, and send a screenshot; the admin confirms with `/ok*` commands.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in the values
python TJ_Danat_bot.py
```

Requires Python 3.8–3.12 (`python-telegram-bot==13.15`).

## Configuration (`.env`)

| Variable | Description |
|---|---|
| `9258175656:9258175656:AAFg8EgB7Zp-Xi-1KLb-IOkaJSupu64oZjo` | Token from @BotFather |
| `7234237886` | Your numeric Telegram user ID |
| `78 308 2010` | Payment number shown to customers |
| `@shoxcybersecurity` | Support contact shown in the menu |

Never commit `.env` or the `data/` folder.

## Admin commands

- `/ok100`, `/ok310`, `/ok520`, `/ok1060`, `/ok1270`, `/ok_week`, `/ok_month` — confirm an order
  (reply to the screenshot, or `/ok100 <user_id>`)
- `/stats` — income and confirmed orders
- `/users` — number of users
- `/sales` — last 20 sales
