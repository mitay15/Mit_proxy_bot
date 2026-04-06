import os
import requests
import random
import time
import socket
import asyncio
import struct

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
URL_LIST = "https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt"

CACHE_TTL = 43200
CACHE = {"proxies": [], "timestamp": 0}

REQUESTS_TIMEOUT = 10


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
            if line.startswith("tg://proxy"):
                proxies.append(line)
                continue

            if line.startswith("https://t.me/proxy"):
                tg = line.replace("https://t.me/", "tg://")
                proxies.append(tg)
                continue

        return proxies
    except:
        return []


# -----------------------------
# ВАЛИДАЦИЯ СЕКРЕТА
# -----------------------------
def valid_secret(secret: str) -> bool:
    if len(secret) != 32:
        return False
    try:
        int(secret, 16)
        return True
    except:
        return False


# -----------------------------
# DNS-ПРОВЕРКА
# -----------------------------
def dns_alive(server: str) -> bool:
    try:
        socket.gethostbyname(server)
        return True
    except:
        return False


# -----------------------------
# MTProto HANDSHAKE
# -----------------------------
async def mtproto_alive(server, port, secret):
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(server, port),
            timeout=3
        )

        # MTProto handshake packet
        # 0xef + random bytes + secret
        packet = b"\xef" + os.urandom(15) + bytes.fromhex(secret)

        writer.write(packet)
        await writer.drain()

        # ждём ответ
        data = await asyncio.wait_for(reader.read(1), timeout=3)

        writer.close()
        try:
            await writer.wait_closed()
        except:
            pass

        return len(data) > 0

    except:
        return False


# -----------------------------
# ПОЛНАЯ ФИЛЬТРАЦИЯ
# -----------------------------
async def filter_alive(proxies):
    good = []

    for p in proxies:
        try:
            server = p.split("server=")[1].split("&")[0]
            port = int(p.split("port=")[1].split("&")[0])
            secret = p.split("secret=")[1]
        except:
            continue

        # 1. секрет должен быть валидным
        if not valid_secret(secret):
            continue

        # 2. DNS должен резолвиться
        if not dns_alive(server):
            continue

        # 3. MTProto handshake
        if await mtproto_alive(server, port, secret):
            good.append(p)

    # fallback
    if not good:
        good = proxies

    return good


# -----------------------------
# КЭШ
# -----------------------------
async def get_cached_proxies():
    now = time.time()

    if now - CACHE["timestamp"] < CACHE_TTL and CACHE["proxies"]:
        return CACHE["proxies"]

    proxies = fetch_proxies()
    if not proxies:
        return CACHE["proxies"]

    alive = await filter_alive(proxies)

    CACHE["proxies"] = alive
    CACHE["timestamp"] = now

    return alive


# -----------------------------
# КОМАНДЫ БОТА
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔥 Рабочий прокси", callback_data="fast")],
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
        await query.edit_message_text(f"🔥 Рабочий прокси:\n{proxies[0]}")

    elif query.data == "top10":
        top = proxies[:10]
        text = "🏎️ Топ‑10 рабочих прокси:\n\n" + "\n\n".join(top)
        await query.edit_message_text(text)


# -----------------------------
# ЗАПУСК
# -----------------------------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не установлен")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()


if __name__ == "__main__":
    main()
