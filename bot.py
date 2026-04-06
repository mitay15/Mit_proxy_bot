import os
import asyncio
import socket
import random
import time
import requests

from pyrogram import Client
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes


# ---------------------------------------------------------
# ДАННЫЕ БЕРЁМ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
# ---------------------------------------------------------
API_ID = int(os.getenv("API_ID"))              # твой API_ID
API_HASH = os.getenv("API_HASH")               # твой API_HASH
SESSION_STRING = os.getenv("SESSION_STRING")   # твой SESSION_STRING
BOT_TOKEN = os.getenv("BOT_TOKEN")             # токен бота
# ---------------------------------------------------------

# Telegram‑каналы с прокси
CHANNELS = [
    "MTProxyList",
    "ProxyMTProto",
    "mtpro_xyz",
    "mtproxies"
]

# GitHub‑источники
GITHUB_SOURCES = [
    "https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS.txt"
]

CACHE_TTL = 3600          # кэш 1 час
MAX_LATENCY_MS = 1500     # максимум 1.5 секунды

# кэш: список словарей вида {"proxy": str, "ping": int}
CACHE = {"proxies": [], "timestamp": 0}


# ---------------------------------------------------------
# ВАЛИДАЦИЯ СЕКРЕТА
# ---------------------------------------------------------
def valid_secret(secret: str) -> bool:
    if len(secret) != 32:
        return False
    try:
        int(secret, 16)
        return True
    except:
        return False


# ---------------------------------------------------------
# DNS‑ПРОВЕРКА
# ---------------------------------------------------------
def dns_alive(server: str) -> bool:
    try:
        socket.gethostbyname(server)
        return True
    except:
        return False


# ---------------------------------------------------------
# ИЗМЕРЕНИЕ LATENCY + MTProto‑HANDSHAKE
# ---------------------------------------------------------
async def measure_proxy(server, port, secret):
    """
    Возвращает ping в миллисекундах или None, если прокси нерабочий/медленный.
    """
    start = time.time()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(server, port),
            timeout=3
        )
    except:
        return None

    connect_time = (time.time() - start) * 1000  # ms

    # MTProto‑handshake
    try:
        packet = b"\xef" + os.urandom(15) + bytes.fromhex(secret)
        writer.write(packet)
        await writer.drain()

        data = await asyncio.wait_for(reader.read(1), timeout=3)

        writer.close()
        try:
            await writer.wait_closed()
        except:
            pass

        if not data:
            return None

        total_time = (time.time() - start) * 1000  # ms

        if total_time > MAX_LATENCY_MS:
            return None

        return int(total_time)

    except:
        try:
            writer.close()
            await writer.wait_closed()
        except:
            pass
        return None


# ---------------------------------------------------------
# ПАРСИНГ TELEGRAM‑КАНАЛОВ
# ---------------------------------------------------------
async def fetch_from_channels():
    app = Client("session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
    await app.start()

    proxies = []

    for channel in CHANNELS:
        try:
            async for msg in app.get_chat_history(channel, limit=50):
                if not msg.text:
                    continue
                lines = msg.text.splitlines()
                for line in lines:
                    if "tg://proxy" in line:
                        proxies.append(line.strip())
        except:
            continue

    await app.stop()
    return proxies


# ---------------------------------------------------------
# ПАРСИНГ GITHUB
# ---------------------------------------------------------
def fetch_from_github():
    proxies = []
    for url in GITHUB_SOURCES:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                continue
            for line in r.text.splitlines():
                line = line.strip()
                if "tg://proxy" in line:
                    proxies.append(line)
                elif "https://t.me/proxy" in line:
                    proxies.append(line.replace("https://t.me/", "tg://"))
        except:
            continue
    return proxies


# ---------------------------------------------------------
# ПОЛНАЯ ФИЛЬТРАЦИЯ + ИЗМЕРЕНИЕ СКОРОСТИ
# ---------------------------------------------------------
async def filter_and_measure(proxies_raw):
    results = []

    for p in proxies_raw:
        try:
            server = p.split("server=")[1].split("&")[0]
            port = int(p.split("port=")[1].split("&")[0])
            secret = p.split("secret=")[1]
        except:
            continue

        if not valid_secret(secret):
            continue

        if not dns_alive(server):
            continue

        ping = await measure_proxy(server, port, secret)
        if ping is None:
            continue

        results.append({"proxy": p, "ping": ping})

    # сортируем по ping (от меньшего к большему)
    results.sort(key=lambda x: x["ping"])
    return results


# ---------------------------------------------------------
# КЭШ
# ---------------------------------------------------------
async def get_proxies():
    now = time.time()

    if now - CACHE["timestamp"] < CACHE_TTL and CACHE["proxies"]:
        return CACHE["proxies"]

    proxies_raw = []

    proxies_raw += fetch_from_github()
    proxies_raw += await fetch_from_channels()

    # убираем дубликаты по строке
    proxies_raw = list(set(proxies_raw))

    measured = await filter_and_measure(proxies_raw)

    CACHE["proxies"] = measured
    CACHE["timestamp"] = now

    return measured


# ---------------------------------------------------------
# TELEGRAM‑БОТ
# ---------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔥 Самый быстрый", callback_data="fast")],
        [InlineKeyboardButton("🎲 Случайный", callback_data="random")],
        [InlineKeyboardButton("🏎️ Топ‑10 быстрых", callback_data="top10")],
    ]
    await update.message.reply_text("Выбери действие:", reply_markup=InlineKeyboardMarkup(keyboard))


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    proxies = await get_proxies()

    if not proxies:
        await query.edit_message_text("Нет доступных прокси.")
        return

    if query.data == "fast":
        best = proxies[0]
        await query.edit_message_text(
            f"🔥 Самый быстрый прокси ({best['ping']} ms):\n{best['proxy']}"
        )

    elif query.data == "random":
        choice = random.choice(proxies)
        await query.edit_message_text(
            f"🎲 Случайный рабочий прокси ({choice['ping']} ms):\n{choice['proxy']}"
        )

    elif query.data == "top10":
        top = proxies[:10]
        lines = []
        for i, item in enumerate(top, start=1):
            lines.append(f"{i}) {item['ping']} ms\n{item['proxy']}")
        text = "🏎️ Топ‑10 самых быстрых прокси:\n\n" + "\n\n".join(lines)
        await query.edit_message_text(text)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()


if __name__ == "__main__":
    main()
