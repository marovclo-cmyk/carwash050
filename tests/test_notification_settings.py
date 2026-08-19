"""
Тесты sessions.py-функций для настроек/лога уведомлений (Stage 24, Phase 6):
get_notification_settings/update_notification_settings/log_notification/
get_notification_log. HTTP-уровень (/api/notification-settings,
/api/notification-log) и триггеры shift_open/shift_close/new_booking
покрыты отдельно в test_notifications_api.py.
"""


def test_get_notification_settings_creates_defaults(sessions_mod):
    settings = sessions_mod.get_notification_settings()

    assert settings["booking_reminders_enabled"] is True
    assert settings["reminder_window_minutes"] == 60
    assert settings["winback_enabled"] is True
    assert settings["winback_cooldown_days"] == 30
    assert settings["shift_notifications_enabled"] is True
    assert settings["new_booking_notifications_enabled"] is True


def test_get_notification_settings_is_singleton(sessions_mod):
    first = sessions_mod.get_notification_settings()
    sessions_mod.update_notification_settings(reminder_window_minutes=45)
    second = sessions_mod.get_notification_settings()

    assert first["reminder_window_minutes"] == 60
    assert second["reminder_window_minutes"] == 45


def test_update_notification_settings_partial(sessions_mod):
    updated = sessions_mod.update_notification_settings(
        booking_reminders_enabled=False, winback_cooldown_days=14)

    assert updated["booking_reminders_enabled"] is False
    assert updated["winback_cooldown_days"] == 14
    # непереданные поля остаются дефолтными
    assert updated["winback_enabled"] is True
    assert updated["reminder_window_minutes"] == 60


def test_update_notification_settings_ignores_none_fields(sessions_mod):
    sessions_mod.update_notification_settings(shift_notifications_enabled=False)
    updated = sessions_mod.update_notification_settings(shift_notifications_enabled=None)

    # None не должен затирать уже сохранённое значение False
    assert updated["shift_notifications_enabled"] is False


def test_log_notification_and_get_notification_log(sessions_mod):
    sessions_mod.log_notification("booking_reminder", "Центр", "Иван Иванов", "текст 1", True)
    sessions_mod.log_notification("client_winback", None, "Пётр Петров", "текст 2", False)

    entries = sessions_mod.get_notification_log()

    assert len(entries) == 2
    # самые свежие первыми
    assert entries[0]["kind"] == "client_winback"
    assert entries[0]["success"] is False
    assert entries[1]["kind"] == "booking_reminder"
    assert entries[1]["success"] is True
    assert entries[1]["branch"] == "Центр"


def test_get_notification_log_filters_by_kind_and_branch(sessions_mod):
    sessions_mod.log_notification("shift_open", "Центр", "Владелец", "открыта", True)
    sessions_mod.log_notification("shift_close", "Центр", "Владелец", "закрыта", True)
    sessions_mod.log_notification("shift_open", "Юг", "Владелец", "открыта", True)

    by_kind = sessions_mod.get_notification_log(kind="shift_open")
    assert len(by_kind) == 2
    assert all(e["kind"] == "shift_open" for e in by_kind)

    by_branch = sessions_mod.get_notification_log(branch="Юг")
    assert len(by_branch) == 1
    assert by_branch[0]["branch"] == "Юг"


def test_get_notification_log_respects_limit(sessions_mod):
    for i in range(5):
        sessions_mod.log_notification("low_stock", "Центр", f"Админ {i}", "текст", True)

    entries = sessions_mod.get_notification_log(limit=2)

    assert len(entries) == 2
