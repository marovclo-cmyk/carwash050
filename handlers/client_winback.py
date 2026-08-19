"""
Периодическая job: win-back-сообщения неактивным клиентам (Stage 23,
Phase 8, второй сценарий GAP-NOTIFY1 — первый, booking reminders, см.
handlers/booking_reminders.py, Stage 22).

Вызывается через app.job_queue.run_daily (см. bot.py) один раз в сутки —
в отличие от booking_reminder_job, здесь нет узкого временного окна,
которое можно проскочить между прогонами (неактивность клиента длится
неделями/месяцами, не минутами), так что ежедневного прогона достаточно
и не нагружает БД лишний раз.

На каждом прогоне, если раздел не выключен в настройках (Stage 24, Phase 6
— sessions.get_notification_settings, "winback_enabled"), выбирает
клиентов, которым пора напомнить о себе, с настроенным cooldown'ом
("winback_cooldown_days", по умолчанию 30 — раньше был захардкоженный
WINBACK_COOLDOWN_DAYS), шлёт каждому по одному сообщению, помечает
отправленным (sessions.mark_client_winback_sent) и логирует попытку
(sessions.log_notification, kind="client_winback") — той же схемой "по
возможности, тихо логируем сбой", что и notify.py и booking_reminders.py.
"""
import logging

import pytz

from sessions import (
    find_clients_due_for_winback, mark_client_winback_sent,
    get_notification_settings, log_notification,
)

log = logging.getLogger("client_winback")

MOSCOW = pytz.timezone("Europe/Moscow")
WINBACK_COOLDOWN_DAYS = 30  # запасное значение, если настройки почему-то недоступны


def _format_winback_text(client: dict) -> str:
    name = (client.get("name") or "").strip()
    greeting = f"{name}, давно вас не видели!" if name else "Давно вас не видели!"
    return f"👋 {greeting} Будем рады видеть вас снова на мойке. Ждём в гости!"


async def client_winback_job(context) -> None:
    try:
        settings = get_notification_settings()
    except Exception as e:
        log.warning("Не удалось получить настройки уведомлений, использую значения по умолчанию: %s", e)
        settings = {"winback_enabled": True, "winback_cooldown_days": WINBACK_COOLDOWN_DAYS}

    if not settings.get("winback_enabled", True):
        return

    cooldown_days = settings.get("winback_cooldown_days") or WINBACK_COOLDOWN_DAYS

    now = datetime_now_moscow_naive()
    try:
        due = find_clients_due_for_winback(now, cooldown_days=cooldown_days)
    except Exception as e:
        log.warning("Не удалось получить клиентов для win-back: %s", e)
        return

    for client in due:
        telegram_id = client.get("telegram_id")
        phone = client.get("phone")
        recipient = (client.get("name") or "").strip() or phone or str(telegram_id)
        try:
            await context.bot.send_message(chat_id=telegram_id, text=_format_winback_text(client))
            mark_client_winback_sent(phone, now)
            _log_winback_safe(recipient, client, success=True)
        except Exception as e:
            # Не роняем весь прогон job'ы из-за одной неудавшейся отправки
            # (клиент заблокировал бота и т.п.) — тихо логируем,
            # last_winback_sent_at НЕ ставим, следующий прогон попробует
            # снова.
            log.warning("Не удалось отправить win-back клиенту %s: %s", phone, e)
            _log_winback_safe(recipient, client, success=False)


def _log_winback_safe(recipient: str, client: dict, success: bool) -> None:
    try:
        log_notification("client_winback", None, recipient, _format_winback_text(client), success)
    except Exception as e:
        log.warning("Не удалось записать win-back в лог уведомлений: %s", e)


def datetime_now_moscow_naive():
    from datetime import datetime
    return datetime.now(MOSCOW).replace(tzinfo=None)
