"""
Тесты выборки клиентов для win-back-сообщения (Stage 23, Phase 8):
sessions.find_clients_due_for_winback / mark_client_winback_sent. Сама
отправка в Telegram (handlers/client_winback.client_winback_job) не
тестируется юнит-тестами — в этой среде нет реального Telegram, см.
PROJECT_BRAIN.

lifecycle_stage ("inactive"/"no_visits"/"new"/"active") вычисляется в
client_summary через datetime.now() (реальное системное время, не
параметр now у find_clients_due_for_winback) — тот же существующий
паттерн, что и у CRM-сегментации/visit_trend, поэтому даты визитов
здесь считаются от реального "сейчас" (NOW), а не от произвольной
фиксированной даты.
"""
from datetime import datetime, timedelta

from config import BRANCHES

BRANCH = BRANCHES[0]
NOW = datetime.now()


def _date_days_ago(days: int) -> str:
    return (NOW - timedelta(days=days)).strftime("%d.%m.%Y")


def test_due_for_inactive_linked_client(sessions_mod):
    sessions_mod.upsert_client_visit("+79992220001", "Клиент А", BRANCH, "А111АА", 500,
                                      date=_date_days_ago(40))
    sessions_mod.link_client_telegram("+79992220001", 600001)

    due = sessions_mod.find_clients_due_for_winback(NOW, cooldown_days=30)

    assert len(due) == 1
    assert due[0]["phone"] == "79992220001"
    assert due[0]["lifecycle_stage"] == "inactive"


def test_not_due_for_active_client(sessions_mod):
    sessions_mod.upsert_client_visit("+79992220002", "Клиент Б", BRANCH, "В222ВВ", 500,
                                      date=_date_days_ago(10))
    sessions_mod.link_client_telegram("+79992220002", 600002)

    due = sessions_mod.find_clients_due_for_winback(NOW, cooldown_days=30)

    assert due == []


def test_not_due_for_client_with_no_visits(sessions_mod):
    # Привязан к Telegram (например, через QR на мойке), но ни разу не
    # приезжал -- "возвращайтесь" тут неуместно, это другой сценарий.
    sessions_mod.link_client_telegram("+79992220003", 600003)

    due = sessions_mod.find_clients_due_for_winback(NOW, cooldown_days=30)

    assert due == []


def test_not_due_without_telegram_link(sessions_mod):
    sessions_mod.upsert_client_visit("+79992220004", "Клиент Г", BRANCH, "Е444ЕЕ", 500,
                                      date=_date_days_ago(40))
    # link_client_telegram не вызывался.

    due = sessions_mod.find_clients_due_for_winback(NOW, cooldown_days=30)

    assert due == []


def test_not_due_when_client_opted_out(sessions_mod):
    sessions_mod.upsert_client_visit("+79992220005", "Клиент Д", BRANCH, "К555КК", 500,
                                      date=_date_days_ago(40))
    sessions_mod.link_client_telegram("+79992220005", 600005)
    sessions_mod.unlink_client_telegram_opt_out(600005)  # /stop

    due = sessions_mod.find_clients_due_for_winback(NOW, cooldown_days=30)

    assert due == []


def test_not_due_within_cooldown_after_recent_send(sessions_mod):
    sessions_mod.upsert_client_visit("+79992220006", "Клиент Е", BRANCH, "М666ММ", 500,
                                      date=_date_days_ago(40))
    sessions_mod.link_client_telegram("+79992220006", 600006)
    sessions_mod.mark_client_winback_sent("+79992220006", NOW)  # только что отправили

    due = sessions_mod.find_clients_due_for_winback(NOW, cooldown_days=30)

    assert due == []


def test_due_again_after_cooldown_expires(sessions_mod):
    sessions_mod.upsert_client_visit("+79992220007", "Клиент Ж", BRANCH, "Н777НН", 500,
                                      date=_date_days_ago(40))
    sessions_mod.link_client_telegram("+79992220007", 600007)
    sessions_mod.mark_client_winback_sent("+79992220007", NOW - timedelta(days=35))  # 35 дней назад

    due = sessions_mod.find_clients_due_for_winback(NOW, cooldown_days=30)

    assert len(due) == 1
    assert due[0]["phone"] == "79992220007"
