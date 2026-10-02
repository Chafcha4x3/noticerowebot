import asyncio
import json
import logging
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

TOKEN = '8744257061:AAH13h8QQY58xzPpvffYcZ__50CYuijRzn4'
DATABASE_PATH = os.getenv("REMINDERS_DB", "reminders.sqlite3")
UTC = timezone.utc
CHECK_INTERVAL_SECONDS = 15
DELIVERY_GRACE = timedelta(minutes=1)

if not TOKEN:
    raise RuntimeError("Установите переменную окружения BOT_TOKEN перед запуском.")

bot = Bot(token=TOKEN)
dp = Dispatcher()


def connect_database() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database() -> None:
    with closing(connect_database()) as connection, connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                times_utc TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS reminder_deliveries (
                reminder_id INTEGER NOT NULL REFERENCES reminders(id) ON DELETE CASCADE,
                scheduled_at TEXT NOT NULL,
                PRIMARY KEY (reminder_id, scheduled_at)
            )"""
        )


def parse_times(value: str) -> list[str]:
    times = []
    for item in value.split(","):
        parsed = datetime.strptime(item.strip(), "%H:%M").time()
        times.append(parsed.strftime("%H:%M"))
    if not times or len(set(times)) != len(times):
        raise ValueError("Укажи неповторяющиеся часы через запятую!\nヾ(⌐■_■)ノ♪")
    return sorted(times)


def get_schedule_dates(
    times_utc: list[str], days: int, now: datetime
) -> tuple[date, date]:
    start_date = now.date()
    if any(
        datetime.combine(start_date, time.fromisoformat(time_text), tzinfo=UTC) <= now
        for time_text in times_utc
    ):
        start_date += timedelta(days=1)
    return start_date, start_date + timedelta(days=days - 1)


@dp.message(CommandStart())
async def start_message(message: Message):
    await message.answer(
        "Приф! ( •̀ ω •́ )✧\n\nСоздавать напоминания нужно по такому формату:\n"
        "/remind ДНИ ЧАСЫ КОММЕНТАРИЙ\n\n Пример:\n"
        "/remind 3 09:00,14:00,20:00 Надо рисовать коммишки!\n"
        "Первое число — срок в днях, список часов в UTC задаёт отправки в день.\n"
        "Я ищо не разобралась до конца как работает времечко, поэтому <b>время нужно писать в UTC+0!!!!!</b> т.е. без учёта часовых поясов.\n"
        "У НАС ЧАСОВОЙ ПОЯС UTC+5!!!\n\n"
        "Команда /myreminders - показывает все созданные напоминания.\n"
        "Команда /cancelreminder ID_напоминания - отменяет напоминание с указанным ID.\n\n"
        "Команда /burger — просто хайп бурегр, я хочу жрать. 🍔", parse_mode="HTML"
    )


@dp.message(Command("remind"))
async def create_reminder(message: Message):
    if message.from_user is None:
        return
    parts = (message.text or "").split(maxsplit=3)
    if len(parts) != 4:
        await message.answer(
            "Формат: /remind ДНИ ЧАСЫ КОММЕНТАРИЙ\n"
            "Пример: /remind 3 09:00,14:00,20:00 Надо рисовать коммишки!",
            parse_mode="HTML"
        )
        return

    try:
        days = int(parts[1])
        if not 1 <= days <= 365:
            raise ValueError
        times_utc = parse_times(parts[2])
    except ValueError:
        await message.answer(
            "ПРОВЕРЬ СРОК (от 1 до 365 дней) и часы в формате ЧЧ:ММ, "
            "например 09:00,14:00,20:00.",
            parse_mode="HTML"
        )
        return

    reminder_text = parts[3].strip()
    if not reminder_text:
        await message.answer("Добавь текст напоминания!ヾ(⌐■_■)ノ♪")
        return

    start_date, end_date = get_schedule_dates(
        times_utc, days, datetime.now(UTC)
    )
    with closing(connect_database()) as connection, connection:
        cursor = connection.execute(
            """INSERT INTO reminders (user_id, text, times_utc, start_date, end_date)
               VALUES (?, ?, ?, ?, ?)""",
            (
                message.from_user.id,
                reminder_text,
                json.dumps(times_utc),
                start_date.isoformat(),
                end_date.isoformat(),
            ),
        )
        reminder_id = cursor.lastrowid

    await message.answer(
        f"Напоминание #{reminder_id} создано на {days} дн.\n"
        f"Отправок в день: {len(times_utc)}; время UTC: {', '.join(times_utc)}."
    )


@dp.message(Command("myreminders"))
async def list_reminders(message: Message):
    if message.from_user is None:
        return
    today = datetime.now(UTC).date().isoformat()
    with closing(connect_database()) as connection, connection:
        reminders = connection.execute(
            """SELECT id, text, times_utc, end_date FROM reminders
               WHERE user_id = ? AND end_date >= ? ORDER BY id""",
            (message.from_user.id, today),
        ).fetchall()

    if not reminders:
        await message.answer("Ты не добавила ни одного напоминания!\nヾ(⌐■_■)ノ♪")
        return

    lines = [
        f"#{row['id']}: {row['text']} | UTC {', '.join(json.loads(row['times_utc']))} "
        f"| до {row['end_date']}"
        for row in reminders
    ]
    await message.answer("\n".join(lines))


@dp.message(Command("cancelreminder"))
async def cancel_reminder(message: Message):
    if message.from_user is None:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /cancelreminder ID")
        return

    with closing(connect_database()) as connection, connection:
        cursor = connection.execute(
            "DELETE FROM reminders WHERE id = ? AND user_id = ?",
            (int(parts[1]), message.from_user.id),
        )
    if cursor.rowcount:
        await message.answer("Напоминание отменено!")
    else:
        await message.answer("Активное напоминание с таким ID не найдено!")


@dp.message(Command("burger"))
async def burger_message(message: Message):
    await message.answer("Вот твой бургер -> 🍔!")


async def send_due_reminders() -> None:
    now = datetime.now(UTC)
    today = now.date()
    with closing(connect_database()) as connection, connection:
        connection.execute("DELETE FROM reminders WHERE end_date < ?", (today.isoformat(),))
        reminders = connection.execute(
            "SELECT * FROM reminders WHERE start_date <= ? AND end_date >= ?",
            (today.isoformat(), today.isoformat()),
        ).fetchall()

    for reminder in reminders:
        for time_text in json.loads(reminder["times_utc"]):
            slot = datetime.combine(today, time.fromisoformat(time_text), tzinfo=UTC)
            if slot > now or now - slot > DELIVERY_GRACE:
                continue

            slot_key = slot.isoformat()
            with closing(connect_database()) as connection, connection:
                delivered = connection.execute(
                    """SELECT 1 FROM reminder_deliveries
                       WHERE reminder_id = ? AND scheduled_at = ?""",
                    (reminder["id"], slot_key),
                ).fetchone()
            if delivered:
                continue

            try:
                await bot.send_message(
                    reminder["user_id"], f"Напоминание: {reminder['text']}"
                )
            except Exception as error:
                logging.error(
                    "Не удалось отправить напоминание #%s (%s)",
                    reminder["id"],
                    type(error).__name__,
                )
                continue

            with closing(connect_database()) as connection, connection:
                connection.execute(
                    "INSERT OR IGNORE INTO reminder_deliveries (reminder_id, scheduled_at) "
                    "VALUES (?, ?)",
                    (reminder["id"], slot_key),
                )


async def reminder_worker() -> None:
    while True:
        try:
            await send_due_reminders()
        except Exception as error:
            logging.error("Ошибка планировщика напоминаний (%s)", type(error).__name__)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def main():
    initialize_database()
    worker = asyncio.create_task(reminder_worker())
    try:
        await dp.start_polling(bot)
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен пользователем.")

