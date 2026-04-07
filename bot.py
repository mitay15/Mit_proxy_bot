import asyncio
import os
import re
import time
import base64
import json

from aiogram import Bot, Dispatcher, executor, types
from pyrogram import Client

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
OWNER_ID = int(os.getenv("OWNER_ID"))

CHANNELS = ["ProxyMTProto", "MTProtoProxies"]

MAX_CONCURRENT = 20
TCP_TIMEOUT = 2
MTP_TIMEOUT = 2

DATA_FILE = "data.json"
UPDATE_INTERVAL = 6 * 60 * 60  # 6 часов

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)

PROXY_DATA = {
    "updated": None,
    "best": None,
    "top10": [],
}


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(PROXY_DATA, f, ensure_ascii=False, indent=2)


def load_data():
    global PROXY_DATA
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                PROXY_DATA = json.load(f)
        except:
            pass


def parse_proxy(text: str):
    text = text.strip()

    if "tg://proxy" in text:
        try:
            server = text.split("server=")[1].split("&")[0]
            port = int(text.split("port=")[1].split("&")[0])
            secret = text.split("secret=")[1].split("&")[0]
            return server, port, secret
        except:
            return None

    if ("Server:" in text or "IP:" in text) and "Port:" in text and "Secret:" in text:
        try:
            if "Server:" in text:
                server = text.split("Server:")[1].split("\n")[0].strip()
            else:
                server = text.split("IP:")[1].split("\n")[0].strip()

            port = int(text.split("Port:")[1].split("\n")[0].strip())
            secret = text.split("Secret:")[1].split("\n")[0].strip()
            return server, port, secret
        except:
            return None

    return None


async def tcp_ping(server, port):
    start = time.time()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(server, port),
            timeout=TCP_TIMEOUT
        )
    except:
        return None

    try:
        writer.close()
        await writer.wait_closed()
    except:
        pass

    return int((time.time() - start) * 1000)


async def mtproto_handshake(server, port, secret):
    start = time.time()

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(server, port),
            timeout=MTP_TIMEOUT
        )
    except:
        return None

    try:
        try:
            key = bytes.fromhex(secret)
        except ValueError:
            s = secret
            while len(s) % 4 != 0:
                s += "="
            key = base64.b64decode(s)

        packet = b"\xef" + os.urandom(15) + key

        writer.write(packet)
        await writer.drain()

        data = await asyncio.wait_for(reader.read(1), timeout=MTP_TIMEOUT)

        writer.close()
        await writer.wait_closed()

        if not data:
            return None

        return int((time.time() - start) * 1000)

    except:
        return None


async def check_proxy(server, port, secret, sem):
    async with sem:
        tcp = await tcp_ping(server, port)
        if tcp is None:
            return None

        mtp = await mtproto_handshake(server, port, secret)
        if mtp is None:
            return None

        return tcp, mtp, server, port, secret


async def fetch_proxies(app: Client):
    proxies = []

    for channel in CHANNELS:
        async for msg in app.get_chat_history(channel, limit=50):
            if not msg.text:
                continue

            parsed = parse_proxy(msg.text)
            if parsed:
                proxies.append(parsed)

    return proxies


async def update_proxies():
    global PROXY_DATA

    app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
    await app.start()

    proxies = await fetch_proxies(app)

    sem = asyncio.Semaphore(MAX_CONCURRENT)
    tasks = [check_proxy(s, p, sec, sem) for s, p, sec in proxies]

    results = [r for r in await asyncio.gather(*tasks) if r]

    if not results:
        PROXY_DATA = {
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "best": None,
            "top10": [],
        }
        save_data()
        await app.stop()
        return

    results.sort(key=lambda x: x[1])

    best = results[0]
    top10 = results[:10]

    best_link = f"tg://proxy?server={best[2]}&port={best[3]}&secret={best[4]}"
    top_links = [
        f"tg://proxy?server={srv}&port={prt}&secret={sec}"
        for _, _, srv, prt, sec in top10
    ]

    PROXY_DATA = {
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "best": best_link,
        "top10": top_links,
    }

    save_data()
    await app.stop()


async def updater_loop():
    load_data()
    await update_proxies()

    while True:
        await asyncio.sleep(UPDATE_INTERVAL)
        await update_proxies()


@dp.message_handler(commands=["start", "proxy"])
async def send_proxies(message: types.Message):
    if not PROXY_DATA["top10"]:
        await message.answer("Пока нет сохранённых прокси. Подожди пару минут.")
        return

    updated = PROXY_DATA["updated"]
    best = PROXY_DATA["best"]
    top10 = PROXY_DATA["top10"]

    text = f"🕒 Обновлено: <b>{updated}</b>\n\n"
    text += "🔥 <b>Самый быстрый:</b>\n" + best + "\n\n"
    text += "🏆 <b>Топ‑10:</b>\n"
    for i, link in enumerate(top10, 1):
        text += f"{i}) {link}\n"

    await message.answer(text)


@dp.message_handler(commands=["info"])
async def info(message: types.Message):
    updated = PROXY_DATA["updated"]
    await message.answer(f"🕒 Последнее обновление: <b>{updated}</b>")


@dp.message_handler(commands=["force"])
async def force(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Только владелец может обновлять вручную.")
        return

    await message.answer("⏳ Обновляю...")
    await update_proxies()
    await message.answer("✅ Готово!")


async def on_startup(_):
    asyncio.create_task(updater_loop())


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
