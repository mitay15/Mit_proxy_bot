import asyncio
import os
import re
import time
import base64
import json

from pyrogram import Client

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

CHANNELS = ["ProxyMTProto", "MTProtoProxies"]

MAX_CONCURRENT = 20
TCP_TIMEOUT = 2
MTP_TIMEOUT = 2

DATA_FILE = "data.json"


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

    if ("server=" in text or "ip=" in text) and "port=" in text and "secret=" in text:
        try:
            if "server=" in text:
                server = text.split("server=")[1].split()[0]
            else:
                server = text.split("ip=")[1].split()[0]

            port = int(text.split("port=")[1].split()[0])
            secret = text.split("secret=")[1].split()[0]
            return server, port, secret
        except:
            return None

    match = re.match(r"([\w\.\-]+)\s+(\d+)\s+([0-9A-Za-z\+\=/]+)", text)
    if match:
        return match.group(1), int(match.group(2)), match.group(3)

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
        print(f"Читаю канал: {channel}")
        async for msg in app.get_chat_history(channel, limit=50):
            if not msg.text:
                continue

            parsed = parse_proxy(msg.text)
            if parsed:
                proxies.append(parsed)

    print(f"Найдено прокси: {len(proxies)}")
    return proxies


async def main():
    app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
    await app.start()

    proxies = await fetch_proxies(app)

    print("Проверяю прокси параллельно...")

    sem = asyncio.Semaphore(MAX_CONCURRENT)
    tasks = [
        check_proxy(server, port, secret, sem)
        for server, port, secret in proxies
    ]

    results = [r for r in await asyncio.gather(*tasks) if r]

    print(f"Рабочих MTProto прокси: {len(results)}")

    if not results:
        data = {
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "best": None,
            "top10": [],
        }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        await app.stop()
        print("Нет доступных прокси, записал пустой результат.")
        return

    results.sort(key=lambda x: x[1])  # по MTProto

    best = results[0]
    top10 = results[:10]

    best_link = f"tg://proxy?server={best[2]}&port={best[3]}&secret={best[4]}"
    top_links = [
        f"tg://proxy?server={srv}&port={prt}&secret={sec}"
        for _, _, srv, prt, sec in top10
    ]

    data = {
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "best": best_link,
        "top10": top_links,
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("Результат записан в data.json")

    await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
