import json
import os
from aiogram import Bot, Dispatcher, executor, types

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "data.json"

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)


def load_data():
    if not os.path.exists(DATA_FILE):
        return None
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None


@dp.message_handler(commands=["start", "proxy"])
async def send_proxies(message: types.Message):
    data = load_data()

    if not data or not data.get("top10"):
        await message.answer(
            "Пока нет сохранённых прокси.\n"
            "Подожди, пока воркер обновит данные (раз в 6 часов)."
        )
        return

    updated = data.get("updated", "неизвестно")
    best = data.get("best")
    top10 = data.get("top10", [])

    text_lines = []
    text_lines.append(f"🕒 Обновлено: <b>{updated}</b>\n")

    if best:
        text_lines.append("🔥 <b>Самый быстрый прокси:</b>")
        text_lines.append(best + "\n")

    text_lines.append("🏆 <b>Топ‑10 прокси:</b>")
    for i, link in enumerate(top10, start=1):
        text_lines.append(f"{i}) {link}")

    await message.answer("\n".join(text_lines))


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
