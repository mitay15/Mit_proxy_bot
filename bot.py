import os
import requests
import json
import random
import time
import socket
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")

URL_LIST = "https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt"
URL_SPEED = "https://raw.githubusercontent.com/SoliSpirit/mtproto/master/speedtest.json"

CACHE_TTL = 43200  # 12 часов
CACHE = {"proxies": [], "speed": {}, "timestamp": 0}


def fetch_proxies():
    txt = requests.get(URL_LIST, timeout=5).text.strip().split("\n")
    return [p for p in txt if p.startswith("tg://")]


def fetch_speed():
    try:
        return requests.get(URL_SPEED, timeout=5).json()
    except:
        return {}


def is_alive(server, port=443, timeout=1.2):
    try:
        sock = socket.create_connection((server, port), timeout=timeout)
        sock.close()
        return True
    except:
        return False


def get_cached():
    now = time.time()
    if now - CACHE["timestamp"] < CACHE_TTL:
        return CACHE["proxies"], CACHE["speed"]

    proxies = fetch_proxies()
    speed = fetch_speed()

    alive = []
    for p in proxies:
        server = p.split("server=")[1].split("&")[0]
        if is_alive(server):
            alive.append(p)

    CACHE["proxies"] = alive
    CACHE["speed"] = speed
    CACHE["timestamp"] = now

    return alive, speed


def get_fastest(proxies, speed, limit=10):
    scored = []
    for p in proxies:
        server = p.split("server=")[1].split("&")[0]
        s = speed.get(server, 0)
        scored.append((p, s))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔥 Быстрый прокси", callback_data="fast")],
        [InlineKeyboardButton("🎲 Случайный", callback_data="random")],
        [InlineKeyboardButton("🏎️ Топ‑10", callback_data="top10")]
    ]
    await update.message.reply_text(
        "Выбери действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    proxies, speed = get_cached()

    if not proxies:
        await query.edit_message_text("Нет доступных прокси.")
        return

    if query.data == "random":
        await query.edit_message_text(random.choice(proxies))

    elif query.data == "fast":
        p, s = get_fastest(proxies, speed, 1)[0]
        await query.edit_message_text(f"🔥 Самый быстрый ({s} Mbps):\n{p}")

    elif query.data == "top10":
        top = get_fastest(proxies, speed, 10)
        text = "🏎️ Топ‑10 быстрых прокси:\n\n"
        for p, s in top:
            text += f"{s} Mbps — {p}\n\n"
        await query.edit_message_text(text)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()


if __name__ == "__main__":
    main()
