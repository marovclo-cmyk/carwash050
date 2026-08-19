"""
Тесты фундамента связки клиента с Telegram (Stage 21, GAP-NOTIFY1):
link_client_telegram / unlink_client_telegram_opt_out /
find_client_by_telegram_id в sessions.py. Бизнес-правила, которые эти
тесты фиксируют, зафиксированы владельцем перед реализацией (см.
PROJECT_BRAIN/CHANGELOG.md Stage 21) — не придуманы.
"""


def test_link_creates_new_client_card_for_unknown_phone(sessions_mod):
    # Клиент делится номером, которого ещё нет в CRM -> карточка создаётся
    # автоматически (бизнес-решение владельца).
    c = sessions_mod.link_client_telegram("+79991230001", 111000001)
    assert c["phone"] == "79991230001"
    assert c["telegram_id"] == 111000001
    assert c["notify_opt_in"] is True
    assert c["visit_count"] == 0  # новая карточка, визитов ещё нет


def test_link_reuses_existing_client_card(sessions_mod):
    sessions_mod.upsert_client_visit("+79991230002", "Инна", "Филиал 1", "Н222НН", 500)
    c = sessions_mod.link_client_telegram("+79991230002", 111000002)
    assert c["telegram_id"] == 111000002
    assert c["notify_opt_in"] is True
    assert c["name"] == "Инна"  # существующая карточка, не перезаписана


def test_relinking_telegram_id_moves_it_from_old_phone(sessions_mod):
    # Один и тот же telegram_id привязывается к другому номеру ->
    # переподключение разрешено (бизнес-решение владельца), старая
    # карточка теряет привязку.
    old = sessions_mod.link_client_telegram("+79991230003", 111000003)
    assert old["telegram_id"] == 111000003

    new = sessions_mod.link_client_telegram("+79991230004", 111000003)
    assert new["telegram_id"] == 111000003
    assert new["notify_opt_in"] is True

    old_reloaded = sessions_mod.find_client("+79991230003")
    assert old_reloaded["telegram_id"] is None
    assert old_reloaded["notify_opt_in"] is False


def test_find_client_by_telegram_id(sessions_mod):
    sessions_mod.link_client_telegram("+79991230005", 111000005)
    found = sessions_mod.find_client_by_telegram_id(111000005)
    assert found is not None
    assert found["phone"] == "79991230005"

    assert sessions_mod.find_client_by_telegram_id(999999999) is None


def test_opt_out_disables_notify_but_keeps_telegram_id(sessions_mod):
    sessions_mod.link_client_telegram("+79991230006", 111000006)
    updated = sessions_mod.unlink_client_telegram_opt_out(111000006)
    assert updated["notify_opt_in"] is False
    assert updated["telegram_id"] == 111000006  # привязка сохранена, не стёрта

    reloaded = sessions_mod.find_client("+79991230006")
    assert reloaded["notify_opt_in"] is False
    assert reloaded["telegram_id"] == 111000006


def test_opt_out_for_unlinked_telegram_id_returns_none(sessions_mod):
    assert sessions_mod.unlink_client_telegram_opt_out(999999998) is None


def test_new_client_defaults_have_no_telegram_link(sessions_mod):
    # Обычная карточка (не через Telegram-flow) — telegram_id/notify_opt_in
    # по умолчанию пустые, ничего не сломано в существующем пути создания.
    c = sessions_mod.upsert_client_visit("+79991230007", "Олег", "Филиал 1", "О777ОО", 500)
    assert c["telegram_id"] is None
    assert c["notify_opt_in"] is False
