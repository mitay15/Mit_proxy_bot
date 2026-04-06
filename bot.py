import os
import requests
import random
import time
import socket
import traceback

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# Токен из переменной окружения Railway
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Источник прокси
URL_LIST = "https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt"

# Настройки
CACHE_TTL = 43200  # 12 часов
CACHE = {"proxies": [], "timestamp": 0, "last_error": None}

CHECK_ALIVE = True          # можно временно выключить для диагностики
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

        return proxies, None

    except Exception as e:
        return [], f"fetch_error: {repr(e)}"


# -----------------------------
# ПРОВЕРКА ДОСТУПНОСТИ
# -----------------------------
def is_alive(server, port=443, timeout=SOCKET_TIMEOUT):
    try:
        sock = socket.create_connection((server, port), timeout=timeout)
        sock.close()
        return True
    except Exception:
        return False


# -----------------------------
# КЭШИРОВАНИЕ
# -----------------------------
def get_cached_proxies():
    now = time.time()

    # Если кэш свежий — возвращаем
    if now - CACHE["timestamp"] < CACHE_TTL and CACHE["proxies"]:
        return CACHE["proxies"], CACHE["last_error"]

    # Иначе обновляем
    proxies, err = fetch_proxies()
    alive = []

    if proxies and CHECK_ALIVE:
        for p in proxies:
            try:
                server = p.split("server=")[1].split("&")[0]
            except Exception:
                continue
            if is_alive(server):
                alive.append(p)
    else:
        alive = proxies.copy()

    # Если после фильтрации пусто — используем весь список
    if not alive and proxies:
        alive = proxies.copy()

    CACHE["proxies"] = alive
    CACHE["timestamp"] = now
    CACHE["last_error"] = err

    return alive, err


# -----------------------------
# КОМАНДЫ БОТА
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔥 Быстрый прокси", callback_data="fast")],
        [InlineKeyboardButton("🎲 Случайный", callback_data="random")],
        [InlineKeyboardButton("🏎️ Топ‑10", callback_data="top10")],
        [InlineKeyboardButton("🛠️ Debug", callback_data="debug")],
    ]
    await update.message.reply_text(
        "Выбери действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        proxies, err = get_cached_proxies()
    except Exception as e:
        await query.edit_message_text(f"Ошибка при получении прокси: {e}")
        return

    if not proxies:
        text = "Нет доступных прокси."
        if err:
            text += f"\nОшибка загрузки: {err}"
        await query.edit_message_text(text)
        return

    if query.data == "random":
        await query.edit_message_text(random.choice(proxies))

    elif query.data == "fast":
        await query.edit_message_text(f"🔥 Быстрый прокси:\n{proxies[0]}")

    elif query.data == "top10":
        top = proxies[:10]
        text = "🏎️ Топ‑10 прокси:\n\n" + "\n\n".join(top)
        await query.edit_message_text(text)

    elif query.data == "debug":
        raw, fetch_err = fetch_proxies()
        alive, _ = get_cached_proxies()

        text = (
            f"Debug info:\n\n"
            f"Всего raw: {len(raw)}\n"
            f"Всего alive: {len(alive)}\n"
            f"Последняя ошибка fetch: {fetch_err}\n\n"
            f"Примеры raw:\n" + ("\n".join(raw[:5]) if raw else "— пусто") + "\n\n"
            f"Примеры alive:\n" + ("\n".join(alive[:5]) if alive else "— пусто")
        )
        await query.edit_message_text(text)


async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    proxies, err = get_cached_proxies()
    text = (
        f"Cached proxies: {len(proxies)}\n"
        f"Last error: {err}\n"
        f"Sample:\n" + ("\n".join(proxies[:5]) if proxies else "— пусто")
    )
    await update.message.reply_text(text)


# -----------------------------
# ЗАПУСК
# -----------------------------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("Переменная окружения BOT_TOKEN не установлена")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()


if __name__ == "__main__":
    main()
