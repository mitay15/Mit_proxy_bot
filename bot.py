import os
import requests
import random
import time
import socket
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# Токен из переменной окружения Railway
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Источник прокси
URL_LIST = "https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt"

# Кэш на 12 часов
CACHE_TTL = 43200
CACHE = {"proxies": [], "timestamp": 0}

REQUESTS_TIMEOUT = 10
SOCKET_TIMEOUT = 3


# -----------------------------
# ЗАГРУЗКА ПРОКСИ
# -----------------------------
def fetch_proxies():
    try:
        resp = requests.get(URL_LIST, timeout=REQUESTS_TIMEOUT)
        resp.raise_for_status()

        lines = [l.strip() for l in resp.text.splitlines() if l.strip()]
        proxies = []

        for line in lines:

            # Формат 1: tg://proxy
            if line.startswith("tg://proxy"):
                proxies.append(line)
                continue

            # Формат 2: https://t.me/proxy
            if line.startswith("https://t.me/proxy"):
                tg = line.replace("https://t.me/", "tg://")
                proxies.append(tg)
                continue

        return proxies

    except Exception:
        return []


# -----------------------------
# АСИНХРОННАЯ ПРОВЕРКА ДОСТУПНОСТИ
# -----------------------------
async def check_proxy(server, port=443, timeout=SOCKET_TIMEOUT):
    try:
        await asyncio.wait_for(asyncio.open_connection(server, port), timeout=timeout)
        return True
    except:
        return False


async def filter_alive(proxies):
    tasks = []
    servers = []

    for p in proxies:
        try:
            server = p.split("server=")[1].split("&")[0]
            servers.append(server)
            tasks.append(check_proxy(server))
        except:
            continue

    if not tasks:
        return proxies

    results = await asyncio.gather(*tasks, return_exceptions=True)

    alive = []
    idx = 0
    for p in proxies:
        try:
            server = p.split("server=")[1].split("&")[0]
        except:
            continue

        if idx < len(results) and results[idx] is True:
            alive.append(p)

        idx += 1

    # fallback: если все "мертвые", отдаём весь список
    if not alive:
        alive = proxies

    return alive


# -----------------------------
# КЭШ
# -----------------------------
async def get_cached_proxies():
    now = time.time()

    if now - CACHE["timestamp"] < CACHE_TTL and CACHE["proxies"]:
        return CACHE["proxies"]

    proxies = fetch_proxies()
    alive = await filter_alive(proxies)

    CACHE["proxies"] = alive
    CACHE["timestamp"] = now

    return alive


# -----------------------------
# КОМАНДЫ БОТА
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔥 Быстрый прокси", callback_data="fast")],
        [InlineKeyboardButton("🎲 Случайный", callback_data="random")],
        [InlineKeyboardButton("🏎️ Топ‑10", callback_data="top10")],
    ]
    await update.message.reply_text(
        "Выбери действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    proxies = await get_cached_proxies()

    if not proxies:
        await query.edit_message_text("Нет доступных прокси.")
        return

    if query.data == "random":
        await query.edit_message_text(random.choice(proxies))

    elif query.data == "fast":
        await query.edit_message_text(f"🔥 Быстрый прокси:\n{proxies[0]}")

    elif query.data == "top10":
        top = proxies[:10]
        text = "🏎️ Топ‑10 прокси:\n\n" + "\n\n".join(top)
        await query.edit_message_text(text)


# -----------------------------
# ЗАПУСК
# -----------------------------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("Переменная окружения BOT_TOKEN не установлена")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()


if __name__ == "__main__":
    main()
