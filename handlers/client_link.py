"""
Клиентский bot-flow привязки Telegram (Stage 21, GAP-NOTIFY1) — фундамент
для будущих уведомлений клиентам (напоминания о записи, win-back для
неактивных). НЕ путать с основным /start для персонала (bot.start /
handlers.admin) — это отдельный, клиентский путь входа по deep-link с
параметром "client" (код/QR на мойке, см. PROJECT_BRAIN/CHANGELOG.md
Stage 21). bot.start() отличает один путь от другого по этому параметру
ДО проверки is_allowed(), чтобы клиент никогда не попадал в
staff-онбординг ("напиши своё имя — отправлю заявку владельцу").

Бизнес-решения, зафиксированные владельцем перед реализацией (не
придуманы):
- клиент делится номером, которого нет в CRM -> карточка создаётся
  автоматически (см. sessions.link_client_telegram);
- этот же telegram_id уже привязан к ДРУГОЙ карточке -> переподключение
  разрешено, старая карточка теряет привязку;
- /stop выключает уведомления (notify_opt_in=False), НЕ стирая сам
  telegram_id — повторное согласие не требует заново делиться контактом.
"""
from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from sessions import (
    find_client_by_telegram_id,
    link_client_telegram,
    unlink_client_telegram_opt_out,
)

CLIENT_START_PAYLOAD = "client"

_CONTACT_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("📱 Поделиться номером", request_contact=True)]],
    resize_keyboard=True, one_time_keyboard=True,
)


async def start_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Клиентская ветка /start (deep-link ?start=client). Если этот
    Telegram-аккаунт уже привязан и подписан — просто подтверждает статус,
    не гоняя клиента через шаг с кнопкой заново."""
    tg_id = update.effective_user.id
    existing = find_client_by_telegram_id(tg_id)
    if existing and existing.get("notify_opt_in"):
        await update.message.reply_text(
            f"👋 Вы уже подключены к уведомлениям автомойки (номер {existing['phone']}).\n"
            "Чтобы отключить — отправьте /stop.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    await update.message.reply_text(
        "👋 Привет! Это бот автомойки — подключите уведомления о записи и "
        "напоминания.\n\nНажмите кнопку ниже, чтобы поделиться номером "
        "телефона — по нему найдём вашу карточку клиента (или создадим "
        "новую, если это ваш первый визит).",
        reply_markup=_CONTACT_KEYBOARD,
    )


async def handle_client_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Реагирует на нажатие кнопки "Поделиться номером". Пересланный ЧУЖОЙ
    контакт (не через кнопку) отклоняется — иначе клиент мог бы привязать
    номер, который ему не принадлежит: у автозаполненного через кнопку
    контакта contact.user_id всегда совпадает с самим отправителем."""
    contact = update.message.contact
    if contact is None:
        return
    if contact.user_id != update.effective_user.id:
        await update.message.reply_text(
            "⚠️ Пожалуйста, поделитесь именно своим номером через кнопку — "
            "пересланный чужой контакт принять нельзя.",
            reply_markup=_CONTACT_KEYBOARD,
        )
        return
    updated = link_client_telegram(contact.phone_number, update.effective_user.id)
    await update.message.reply_text(
        f"✅ Готово! Номер {updated['phone']} подключён к уведомлениям автомойки.\n"
        "Чтобы отключить — отправьте /stop.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def stop_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stop — выключает уведомления для этого Telegram-аккаунта."""
    updated = unlink_client_telegram_opt_out(update.effective_user.id)
    if updated is None:
        await update.message.reply_text("Вы ещё не подключали уведомления — отключать нечего.")
        return
    await update.message.reply_text(
        f"🔕 Уведомления для номера {updated['phone']} отключены. "
        "Чтобы включить снова — отправьте /start и поделитесь номером ещё раз."
    )
