"""
Отправка уведомлений пользователю от имени бота (например, когда его
назначили админом филиала или добавили как сотрудника с доступом).
Работает "по возможности": если отправка не удалась (бот не может писать
пользователю, пока тот не запустил бота — ограничение Telegram) — тихо
логируем и не роняем запрос.

Stage 24 (Phase 6): опциональные kind/branch/recipient_label — если
переданы, реальный результат отправки (success — фактический успех/
неуспех в Telegram, не просто факт постановки в очередь) пишется в
NotificationLog через sessions.log_notification для дашборда на
notifications.html. Вызовы без kind (если такие остались) ведут себя
как раньше — просто не логируются.
"""
import asyncio
import logging

from telegram import Bot
from telegram.error import TelegramError

from config import TOKEN

log = logging.getLogger("notify")
_bot = Bot(token=TOKEN)


async def _send(user_id: int, text: str) -> bool:
    try:
        await _bot.send_message(chat_id=user_id, text=text)
        return True
    except TelegramError as e:
        log.warning("Не удалось отправить уведомление %s: %s", user_id, e)
        return False


def notify_user(user_id: int, text: str, *, kind: str | None = None,
                 branch: str | None = None, recipient_label: str | None = None) -> None:
    """Fire-and-forget: не блокирует ответ API, если отправка зависнет/упадёт.

    kind: если задан, попытка логируется в NotificationLog после реальной
    отправки (успешной или нет) — см. докстринг модуля. branch/
    recipient_label — контекст для дашборда (recipient_label по умолчанию —
    просто user_id, если явно не передан человекочитаемый вариант)."""
    if not user_id:
        return

    async def _send_and_log():
        ok = await _send(user_id, text)
        if kind:
            try:
                from sessions import log_notification
                log_notification(kind, branch, recipient_label or str(user_id), text, ok)
            except Exception as e:
                log.warning("Не удалось записать уведомление в лог: %s", e)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_send_and_log())
        else:
            loop.run_until_complete(_send_and_log())
    except RuntimeError:
        asyncio.run(_send_and_log())
