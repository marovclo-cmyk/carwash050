"""
Тесты выборки записей для напоминания клиенту (Stage 22, Phase 8):
sessions.find_bookings_due_for_reminder / mark_booking_reminder_sent, и
сброс reminder_sent при переносе записи в update_booking. Сама отправка в
Telegram (handlers/booking_reminders.booking_reminder_job) не тестируется
юнит-тестами — в этой среде нет реального Telegram, см. PROJECT_BRAIN.
"""
from datetime import datetime

from config import BRANCHES

BRANCH = BRANCHES[0]
DATE = "01.01.2099"          # намеренно не сегодня, тем же принципом, что и
                              # test_bookings_api.py FIXED_DATE — не должно
                              # совпасть со случайным "сегодня" тестового рана
NOW = datetime(2099, 1, 1, 9, 0)  # фиксированный "текущий момент" для тестов


def _make_booking(sessions_mod, phone: str = "", **overrides):
    payload = dict(
        branch=BRANCH, date=DATE, box=1, start_time="09:45", end_time="10:45",
        phone=phone, client_name="Клиент Тестов", status="waiting",
    )
    payload.update(overrides)
    return sessions_mod.create_booking(**payload)


def test_due_when_within_window_and_client_linked(sessions_mod):
    sessions_mod.link_client_telegram("+79991110001", 500001)
    _make_booking(sessions_mod, phone="+79991110001", start_time="09:45")  # через 45 мин

    due = sessions_mod.find_bookings_due_for_reminder(NOW, window_minutes=60)

    assert len(due) == 1
    assert due[0]["telegram_id"] == 500001
    assert due[0]["booking"]["start_time"] == "09:45"


def test_not_due_when_outside_window(sessions_mod):
    sessions_mod.link_client_telegram("+79991110002", 500002)
    _make_booking(sessions_mod, phone="+79991110002", start_time="11:00")  # через 2 часа

    due = sessions_mod.find_bookings_due_for_reminder(NOW, window_minutes=60)

    assert due == []


def test_not_due_when_already_started(sessions_mod):
    sessions_mod.link_client_telegram("+79991110003", 500003)
    _make_booking(sessions_mod, phone="+79991110003", start_time="08:00")  # уже наступило

    due = sessions_mod.find_bookings_due_for_reminder(NOW, window_minutes=60)

    assert due == []


def test_not_due_without_client_link(sessions_mod):
    # Телефон записи есть, но карточка клиента не привязана к Telegram.
    _make_booking(sessions_mod, phone="+79991110004", start_time="09:45")

    due = sessions_mod.find_bookings_due_for_reminder(NOW, window_minutes=60)

    assert due == []


def test_not_due_when_client_opted_out(sessions_mod):
    sessions_mod.link_client_telegram("+79991110005", 500005)
    sessions_mod.unlink_client_telegram_opt_out(500005)  # /stop
    _make_booking(sessions_mod, phone="+79991110005", start_time="09:45")

    due = sessions_mod.find_bookings_due_for_reminder(NOW, window_minutes=60)

    assert due == []


def test_not_due_for_ineligible_status(sessions_mod):
    sessions_mod.link_client_telegram("+79991110006", 500006)
    _make_booking(sessions_mod, phone="+79991110006", start_time="09:45", status="done")

    due = sessions_mod.find_bookings_due_for_reminder(NOW, window_minutes=60)

    assert due == []


def test_mark_sent_excludes_from_next_selection(sessions_mod):
    sessions_mod.link_client_telegram("+79991110007", 500007)
    booking = _make_booking(sessions_mod, phone="+79991110007", start_time="09:45")

    sessions_mod.mark_booking_reminder_sent(booking["id"])
    due = sessions_mod.find_bookings_due_for_reminder(NOW, window_minutes=60)

    assert due == []


def test_reschedule_resets_reminder_sent(sessions_mod):
    sessions_mod.link_client_telegram("+79991110008", 500008)
    booking = _make_booking(sessions_mod, phone="+79991110008", start_time="09:45")
    sessions_mod.mark_booking_reminder_sent(booking["id"])

    # Перенос записи на другое время -> напоминание должно уйти заново.
    sessions_mod.update_booking(booking["id"], start_time="09:50")

    due = sessions_mod.find_bookings_due_for_reminder(NOW, window_minutes=60)
    assert len(due) == 1
    assert due[0]["booking"]["id"] == booking["id"]


def test_unrelated_field_update_does_not_reset_reminder_sent(sessions_mod):
    sessions_mod.link_client_telegram("+79991110009", 500009)
    booking = _make_booking(sessions_mod, phone="+79991110009", start_time="09:45")
    sessions_mod.mark_booking_reminder_sent(booking["id"])

    sessions_mod.update_booking(booking["id"], comment="перезвонить")

    due = sessions_mod.find_bookings_due_for_reminder(NOW, window_minutes=60)
    assert due == []
