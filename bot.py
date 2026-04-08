# --- START: debug single instance guard ---
import socket, sys, os, subprocess, time

LOCK_ADDR = ("127.0.0.1", 9999)

def dump_debug_info(reason):
    print("=== SINGLE INSTANCE GUARD ===")
    print("Reason:", reason)
    print("PID:", os.getpid())
    try:
        out = subprocess.check_output(["ps", "aux"], stderr=subprocess.STDOUT, text=True)
        print("--- ps aux ---")
        print(out)
    except Exception as e:
        print("ps aux failed:", e)
    print("=== END DEBUG ===")
    sys.stdout.flush()

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(LOCK_ADDR)
    s.listen(1)
    print(f"Port lock acquired on {LOCK_ADDR[0]}:{LOCK_ADDR[1]}, PID={os.getpid()}")
    sys.stdout.flush()
except OSError:
    dump_debug_info("port already bound — exiting")
    sys.exit(0)
# --- END: debug single instance guard ---

# --- START: tiny HTTP server for Railway healthcheck ---
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

class Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def start_ping_server():
    server = HTTPServer(("0.0.0.0", 8080), Ping)
    server.serve_forever()

threading.Thread(target=start_ping_server, daemon=True).start()
# --- END: tiny HTTP server ---

# --- YOUR BOT CODE STARTS HERE ---
# (вставляй сюда свой bot.py, который я тебе дал ранее)
# Полностью без изменений, кроме добавления этого блока сверху.

import asyncio
import os
import sys
import time
import re
import base64
import json
import aiohttp
import socket
import struct

from aiogram import Bot, Dispatcher, executor, types
from pyrogram import Client

# ============================================================
#   ЖЕЛЕЗОБЕТОННАЯ ЗАЩИТА ОТ ДВОЙНОГО ЗАПУСКА (PORT LOCK)
# ============================================================

def ensure_single_instance():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 9999))
    except OSError:
        print("⚠️ Another instance already running. Exiting.")
        sys.exit(0)

ensure_single_instance()

# ============================================================
#   НАСТРОЙКИ
# ============================================================

time.sleep(5)

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
OWNER_ID = int(os.getenv("OWNER_ID"))

CHANNELS = ["ProxyMTProto", "MTProtoProxies"]

MAX_CONCURRENT = 20
TCP_TIMEOUT = 2
MTP_TIMEOUT = 2
SOCKS_TIMEOUT = 3

DATA_FILE = "data.json"
UPDATE_INTERVAL = 6 * 60 * 60  # 6 часов

TELEGRAM_DC_IP = "149.154.167.51"
TELEGRAM_DC_PORT = 443

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)

PROXY_DATA = {
    "updated": None,
    "best_mtproto": None,
    "best_socks5": None,
    "top10_mtproto": [],
    "top10_socks5": [],
    "bad": []
}

# ============================================================
#   ФАЙЛЫ
# ============================================================

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

# ============================================================
#   ПАРСИНГ ПРОКСИ
# ============================================================

def parse_mtproto(text: str):
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


def parse_socks5(text: str):
    text = text.strip()

    m = re.match(r"socks5://(.+?):(\d+)", text)
    if m:
        return {"ip": m.group(1), "port": int(m.group(2))}

    m = re.match(r"(\d+\.\d+\.\d+\.\d+):(\d+)", text)
    if m:
        return {"ip": m.group(1), "port": int(m.group(2))}

    return None

# ============================================================
#   ЖЁСТКАЯ ПРОВЕРКА SOCKS5 (CONNECT → DC2 → MTProto)
# ============================================================

async def check_socks5_strict(proxy, sem):
    async with sem:
        ip = proxy["ip"]
        port = proxy["port"]

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=SOCKS_TIMEOUT
            )
        except:
            return None

        try:
            # Greeting
            writer.write(b"\x05\x01\x00")
            await writer.drain()
            resp = await asyncio.wait_for(reader.read(2), timeout=SOCKS_TIMEOUT)
            if resp != b"\x05\x00":
                writer.close()
                return None

            # CONNECT → Telegram DC2
            req = b"\x05\x01\x00\x01" + socket.inet_aton(TELEGRAM_DC_IP) + struct.pack(">H", TELEGRAM_DC_PORT)
            writer.write(req)
            await writer.drain()

            resp = await asyncio.wait_for(reader.read(10), timeout=SOCKS_TIMEOUT)
            if len(resp) < 2 or resp[1] != 0x00:
                writer.close()
                return None

            # Теперь туннель открыт → отправляем MTProto handshake
            start = time.time()

            packet = b"\xef" + os.urandom(15)
            writer.write(packet)
            await writer.drain()

            data = await asyncio.wait_for(reader.read(1), timeout=MTP_TIMEOUT)

            writer.close()
            await writer.wait_closed()

            if not data:
                return None

            return int((time.time() - start) * 1000)

        except:
            try:
                writer.close()
            except:
                pass
            return None

# ============================================================
#   ПРОВЕРКА MTProto
# ============================================================

async def tcp_ping(server, port):
    start = time.time()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(server, port), timeout=TCP_TIMEOUT)
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
        reader, writer = await asyncio.wait_for(asyncio.open_connection(server, port), timeout=MTP_TIMEOUT)
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


async def check_mtproto(server, port, secret, sem):
    async with sem:
        tcp = await tcp_ping(server, port)
        if tcp is None:
            return None

        mtp = await mtproto_handshake(server, port, secret)
        if mtp is None:
            return None

        return mtp

# ============================================================
#   СБОР ПРОКСИ
# ============================================================

async def fetch_mtproto(app: Client):
    proxies = []

    for channel in CHANNELS:
        async for msg in app.get_chat_history(channel, limit=50):
            if not msg.text:
                continue

            parsed = parse_mtproto(msg.text)
            if parsed:
                proxies.append(parsed)

    return proxies


async def fetch_socks5():
    urls = [
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
        "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5&timeout=2000&country=all"
    ]

    proxies = []

    async with aiohttp.ClientSession() as session:
        for url in urls:
            try:
                async with session.get(url, timeout=5) as resp:
                    text = await resp.text()
                    for line in text.splitlines():
                        p = parse_socks5(line)
                        if p:
                            proxies.append(p)
            except:
                pass

    return proxies

# ============================================================
#   ОБНОВЛЕНИЕ ПРОКСИ
# ============================================================

async def update_proxies():
    global PROXY_DATA

    async with Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING) as app:
        mtproto_list = await fetch_mtproto(app)

    socks_list = await fetch_socks5()

    sem = asyncio.Semaphore(MAX_CONCURRENT)

    # MTProto
    mt_tasks = [
        check_mtproto(s, p, sec, sem)
        for s, p, sec in mtproto_list
        if f"{s}:{p}:{sec}" not in PROXY_DATA["bad"]
    ]

    mt_results = await asyncio.gather(*mt_tasks)
    mt_good = []

    for (proxy, result) in zip(mtproto_list, mt_results):
        if result:
            mt_good.append((result, proxy))
        else:
            PROXY_DATA["bad"].append(f"{proxy[0]}:{proxy[1]}:{proxy[2]}")

    mt_good.sort(key=lambda x: x[0])
    top10_mtproto = mt_good[:10]

    # SOCKS5 (строгая проверка)
    socks_tasks = [
        check_socks5_strict(p, sem)
        for p in socks_list
        if f"{p['ip']}:{p['port']}" not in PROXY_DATA["bad"]
    ]

    socks_results = await asyncio.gather(*socks_tasks)
    socks_good = []

    for (proxy, result) in zip(socks_list, socks_results):
        if result:
            socks_good.append((result, proxy))
        else:
            PROXY_DATA["bad"].append(f"{proxy['ip']}:{proxy['port']}")

    socks_good.sort(key=lambda x: x[0])
    top10_socks = socks_good[:10]

    # Формирование ссылок
    best_mtproto = None
    if top10_mtproto:
        _, (s, p, sec) = top10_mtproto[0]
        best_mtproto = f"tg://proxy?server={s}&port={p}&secret={sec}"

    best_socks = None
    if top10_socks:
        _, proxy = top10_socks[0]
        ip = proxy["ip"]
        port = proxy["port"]
        best_socks = f"tg://socks?server={ip}&port={port}"

    PROXY_DATA["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    PROXY_DATA["best_mtproto"] = best_mtproto
    PROXY_DATA["best_socks5"] = best_socks

    PROXY_DATA["top10_mtproto"] = [
        f"tg://proxy?server={s}&port={p}&secret={sec}"
        for _, (s, p, sec) in top10_mtproto
    ]

    PROXY_DATA["top10_socks5"] = [
        f"tg://socks?server={p['ip']}&port={p['port']}"
        for _, p in top10_socks
    ]

    save_data()

# ============================================================
#   ЦИКЛ ОБНОВЛЕНИЯ
# ============================================================

async def updater_loop():
    load_data()
    await update_proxies()

    while True:
        await asyncio.sleep(UPDATE_INTERVAL)
        await update_proxies()

# ============================================================
#   КОМАНДЫ БОТА
# ============================================================

@dp.message_handler(commands=["start", "proxy"])
async def send_proxies(message: types.Message):
    updated = PROXY_DATA["updated"]

    text = f"🕒 Обновлено: <b>{updated}</b>\n\n"

    text += "🔥 <b>Лучший MTProto:</b>\n"
    text += (PROXY_DATA["best_mtproto"] or "Нет рабочих") + "\n\n"

    text += "🏆 <b>Топ‑10 MTProto:</b>\n"
    for i, link in enumerate(PROXY_DATA["top10_mtproto"], 1):
        text += f"{i}) {link}\n"

    text += "\n🟦 <b>Лучший SOCKS5:</b>\n"
    text += (PROXY_DATA["best_socks5"] or "Нет рабочих") + "\n\n"

    text += "🟩 <b>Топ‑10 SOCKS5:</b>\n"
    for i, link in enumerate(PROXY_DATA["top10_socks5"], 1):
        text += f"{i}) {link}\n"

    await message.answer(text)


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
