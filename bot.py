import os
import requests
import random
import time
import socket

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# Токен берём из переменной окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Источник прокси
URL_LIST = "https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt"

# Кэш на 12 часов
CACHE_TTL = 43200  # 12 часов
CACHE = {
    "proxies": [],
    "timestamp": 0,
}


def fetch_proxies():
    """Загрузка списка прокси из GitHub."""
    resp = requests.get(URL_LIST, timeout=10)
    resp.raise_for_status()
    lines = resp.text.strip().split("\n")
    proxies = [p for p in lines if p.startswith("tg://")]
    return proxies


def is_alive(server, port=443, timeout=3):
    """Проверка доступности сервера по порту 443."""
    try:
        sock = socket.create_connection((server, port), timeout=timeout)
        sock.close()
        return True
    except Exception:
        return False


def get_cached_proxies():
    """Возвращает список прокси из кэша или обновляет его."""
    now = time.time()
    # если кэш ещё живой — возвращаем его
    if now - CACHE["timestamp"] < CACHE_TTL and CACHE["proxies"]:
        return CACHE["proxies"]

    # иначе обновляем
    try:
        proxies = fetch_proxies()
    except Exception:
        # если вообще не смогли получить — возвращаем то, что было
        return CACHE["proxies"]

    alive = []
    for p in proxies:
        try:
            server = p.split("server=")[1].split("&")[0]
        except IndexError:
            continue
        if is_alive(server):
            alive.append(p)

    # если все "мертвые" — используем весь список как есть
    if not alive:
        alive = proxies

    CACHE["proxies"] = alive
    CACHE["timestamp"] = now
    return alive


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

    proxies = get_cached_proxies()

    if not proxies:
        await query.edit_message_text("Нет доступных прокси.")
        return

    if query.data == "random":
        p = random.choice(proxies)
        await query.edit_message_text(p)

    elif query.data == "fast":
        # считаем, что первый в списке — условно "быстрый"
        p = proxies[0]
        await query.edit_message_text(f"🔥 Быстрый прокси:\n{p}")

    elif query.data == "top10":
        top = proxies[:10]
        text = "🏎️ Топ‑10 прокси:\n\n" + "\n\n".join(top)
        await query.edit_message_text(text)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Переменная окружения BOT_TOKEN не установлена")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()


if __name__ == "__main__":
    main()
