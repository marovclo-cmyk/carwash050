"""
Периодическая job: напоминания клиентам о предстоящей записи (Stage 22,
Phase 8, поверх фундамента связки клиент↔Telegram из Stage 21).

Вызывается через app.job_queue.run_repeating (см. bot.py) каждые
REMINDER_POLL_INTERVAL_SECONDS (это по-прежнему константа — частота опроса
job'ы, не бизнес-настройка). На каждом прогоне, если раздел не выключен в
настройках (Stage 24, Phase 6 — sessions.get_notification_settings,
"booking_reminders_enabled"), выбирает записи, до начала которых осталось
не больше настроенного окна ("reminder_window_minutes", по умолчанию 60 —
раньше был захардкоженный REMINDER_WINDOW_MINUTES), у клиента которых есть
привязанный и согласившийся на уведомления Telegram-аккаунт
(sessions.find_bookings_due_for_reminder), шлёт каждой по одному сообщению,
помечает как отправленную (sessions.mark_booking_reminder_sent) и логирует
попытку (sessions.log_notification, kind="booking_reminder") — той же
схемой "по возможности, тихо логируем сбой", что и notify.py.

Опрос идёт заметно чаще окна напоминания (5 мин против 60 по умолчанию),
чтобы запись, до которой остаётся ровно ~окно минут, не проскочила мимо
между двумя прогонами.
"""
import logging

import pytz

from sessions import (
    find_bookings_due_for_reminder, mark_booking_reminder_sent,
    get_notification_settings, log_notification,
)

log = logging.getLogger("booking_reminders")

MOSCOW = pytz.timezone("Europe/Moscow")
REMINDER_WINDOW_MINUTES = 60  # запасное значение, если настройки почему-то недоступны
REMINDER_POLL_INTERVAL_SECONDS = 5 * 60


def _format_reminder_text(booking: dict) -> str:
    branch = booking.get("branch") or ""
    time_part = booking.get("start_time") or ""
    branch_part = f", {branch}" if branch else ""
    return f"⏰ Напоминаем: сегодня в {time_part}{branch_part} у вас запись на мойку. Ждём вас!"


async def booking_reminder_job(context) -> None:
    try:
        settings = get_notification_settings()
    except Exception as e:
        log.warning("Не удалось получить настройки уведомлений, использую значения по умолчанию: %s", e)
        settings = {"booking_reminders_enabled": True, "reminder_window_minutes": REMINDER_WINDOW_MINUTES}

    if not settings.get("booking_reminders_enabled", True):
        return

    window_minutes = settings.get("reminder_window_minutes") or REMINDER_WINDOW_MINUTES

    # naive datetime без tzinfo — та же форма, что hранится в
    # BookingModel.date/start_time (без часового пояса), сравнение идёт
    # по московскому времени (тот же пояс, что у существующего reminder_job
    # в handlers/reports.py).
    now = datetime_now_moscow_naive()
    try:
        due = find_bookings_due_for_reminder(now, window_minutes=window_minutes)
    except Exception as e:
        log.warning("Не удалось получить записи для напоминаний: %s", e)
        return

    for item in due:
        booking = item["booking"]
        telegram_id = item["telegram_id"]
        recipient = booking.get("client_name") or booking.get("car") or str(telegram_id)
        try:
            await context.bot.send_message(chat_id=telegram_id, text=_format_reminder_text(booking))
            mark_booking_reminder_sent(booking["id"])
            _log_reminder_safe(booking.get("branch"), recipient, booking, success=True)
        except Exception as e:
            # Не роняем весь прогон job'ы из-за одной неудавшейся отправки
            # (например, клиент ещё не запускал бота с этим telegram_id, или
            # заблокировал его) — тихо логируем, reminder_sent НЕ ставим, так
            # что следующий прогон попробует снова, пока запись не наступит.
            log.warning("Не удалось отправить напоминание о записи %s: %s", booking.get("id"), e)
            _log_reminder_safe(booking.get("branch"), recipient, booking, success=False)


def _log_reminder_safe(branch, recipient: str, booking: dict, success: bool) -> None:
    try:
        log_notification("booking_reminder", branch, recipient, _format_reminder_text(booking), success)
    except Exception as e:
        log.warning("Не удалось записать напоминание в лог уведомлений: %s", e)


def datetime_now_moscow_naive():
    from datetime import datetime
    return datetime.now(MOSCOW).replace(tzinfo=None)
