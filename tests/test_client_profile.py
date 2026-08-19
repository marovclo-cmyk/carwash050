"""
Тесты обогащённого профиля клиента (GAP-CRM2, Phase 7, этап 1):
avg_check, favorite_branch, favorite_service, lifecycle_stage — все
вычисляются в sessions.client_summary() поверх уже существующих
visits/discount_percent, никаких новых полей в БД не добавлено.
"""
from datetime import datetime, timedelta

from config import BRANCHES

BRANCH = BRANCHES[0]
BRANCH_2 = BRANCHES[1] if len(BRANCHES) > 1 else BRANCH


def _date(days_ago: int) -> str:
    return (datetime.now() - timedelta(days=days_ago)).strftime("%d.%m.%Y")


def test_no_visits_client_has_no_visits_lifecycle(sessions_mod):
    # Карточка клиента без единого визита возникает, например, при
    # импорте контактов (import_contact_car_labels) — заводит ClientModel
    # с пустым visits, но клиент ещё не приезжал.
    sessions_mod.import_contact_car_labels([("+79991110000", "Camry")])
    c = sessions_mod.find_client("+79991110000")
    assert c["visit_count"] == 0
    assert c["lifecycle_stage"] == "no_visits"
    assert c["avg_check"] == 0
    assert c["favorite_branch"] is None
    assert c["favorite_service"] is None


def test_single_recent_visit_is_new(sessions_mod):
    c = sessions_mod.upsert_client_visit(
        "+79991110001", "Игорь", BRANCH, "А111АА", 500, date=_date(2),
    )
    assert c["visit_count"] == 1
    assert c["lifecycle_stage"] == "new"
    assert c["avg_check"] == 500


def test_single_old_visit_is_inactive_not_new(sessions_mod):
    """Приоритет: давность важнее, чем "это был единственный визит" —
    иначе клиент, который был один раз полгода назад, вечно числился бы
    "новым" вместо "требует внимания"."""
    c = sessions_mod.upsert_client_visit(
        "+79991110002", "Олег", BRANCH, "Б222ББ", 500, date=_date(45),
    )
    assert c["visit_count"] == 1
    assert c["lifecycle_stage"] == "inactive"


def test_two_recent_visits_is_active(sessions_mod):
    sessions_mod.upsert_client_visit("+79991110003", "Аня", BRANCH, "В333ВВ", 500, date=_date(10))
    c = sessions_mod.upsert_client_visit("+79991110003", "Аня", BRANCH, "В333ВВ", 700, date=_date(1))
    assert c["visit_count"] == 2
    assert c["lifecycle_stage"] == "active"
    assert c["avg_check"] == round((500 + 700) / 2)


def test_visit_30_plus_days_ago_is_inactive(sessions_mod):
    sessions_mod.upsert_client_visit("+79991110004", "Света", BRANCH, "Г444ГГ", 500, date=_date(10))
    c = sessions_mod.upsert_client_visit("+79991110004", "Света", BRANCH, "Г444ГГ", 500, date=_date(31))
    assert c["lifecycle_stage"] == "inactive"


def test_favorite_branch_and_service_are_most_common(sessions_mod):
    phone = "+79991110005"
    sessions_mod.upsert_client_visit(phone, "Марат", BRANCH, "Д555ДД", 500, service="Мойка кузова")
    sessions_mod.upsert_client_visit(phone, "Марат", BRANCH, "Д555ДД", 600, service="Мойка кузова")
    sessions_mod.upsert_client_visit(phone, "Марат", BRANCH_2, "Д555ДД", 700, service="Химчистка")
    c = sessions_mod.find_client(phone)
    assert c["favorite_branch"] == BRANCH
    assert c["favorite_service"] == "Мойка кузова"


def test_favorite_service_none_when_never_recorded(sessions_mod):
    """Старые визиты (до добавления поля service) не ломают подсчёт —
    просто нет фаворита."""
    c = sessions_mod.upsert_client_visit("+79991110006", "Данил", BRANCH, "Е666ЕЕ", 500)
    assert c["favorite_service"] is None
    assert c["favorite_branch"] == BRANCH


def test_visit_trend_has_six_months_oldest_first(sessions_mod):
    c = sessions_mod.upsert_client_visit(
        "+79991110008", "Тимур", BRANCH, "З888ЗЗ", 500, date=_date(0),
    )
    trend = c["visit_trend"]
    assert len(trend) == 6
    # текущий месяц — последний бакет, и в нём должен быть посчитан визит
    assert trend[-1]["count"] == 1
    assert all("label" in t and "count" in t for t in trend)


def test_visit_trend_counts_by_month_ignores_older(sessions_mod):
    phone = "+79991110009"
    sessions_mod.upsert_client_visit(phone, "Юля", BRANCH, "И999ИИ", 500, date=_date(0))
    sessions_mod.upsert_client_visit(phone, "Юля", BRANCH, "И999ИИ", 500, date=_date(0))
    # визит за пределами 6-месячного окна не должен попасть ни в один бакет
    sessions_mod.upsert_client_visit(phone, "Юля", BRANCH, "И999ИИ", 500, date=_date(400))
    c = sessions_mod.find_client(phone)
    trend = c["visit_trend"]
    assert trend[-1]["count"] == 2
    assert sum(t["count"] for t in trend) == 2


def test_visit_trend_all_zero_for_no_visits_client(sessions_mod):
    sessions_mod.import_contact_car_labels([("+79991110010", "Solaris")])
    c = sessions_mod.find_client("+79991110010")
    assert len(c["visit_trend"]) == 6
    assert sum(t["count"] for t in c["visit_trend"]) == 0


def test_service_breakdown_top_three_ordered_by_count(sessions_mod):
    phone = "+79991110011"
    sessions_mod.upsert_client_visit(phone, "Олег", BRANCH, "К111КК", 500, service="Мойка")
    sessions_mod.upsert_client_visit(phone, "Олег", BRANCH, "К111КК", 500, service="Мойка")
    sessions_mod.upsert_client_visit(phone, "Олег", BRANCH, "К111КК", 500, service="Химчистка")
    sessions_mod.upsert_client_visit(phone, "Олег", BRANCH, "К111КК", 500, service="Полировка")
    sessions_mod.upsert_client_visit(phone, "Олег", BRANCH, "К111КК", 500, service="Полировка")
    sessions_mod.upsert_client_visit(phone, "Олег", BRANCH, "К111КК", 500, service="Полировка")
    c = sessions_mod.find_client(phone)
    breakdown = c["service_breakdown"]
    assert len(breakdown) == 3
    assert [s["service"] for s in breakdown] == ["Полировка", "Мойка", "Химчистка"]
    assert [s["count"] for s in breakdown] == [3, 2, 1]
    # favorite_service остаётся согласован с первым местом в breakdown
    assert c["favorite_service"] == breakdown[0]["service"]


def test_service_breakdown_limited_to_three_distinct_services(sessions_mod):
    phone = "+79991110012"
    for service in ["Мойка", "Химчистка", "Полировка", "Шиномонтаж"]:
        sessions_mod.upsert_client_visit(phone, "Инна", BRANCH, "Л222ЛЛ", 500, service=service)
    c = sessions_mod.find_client(phone)
    # 4 разных услуги в истории, но в топ попадают только 3
    assert len(c["service_breakdown"]) == 3


def test_service_breakdown_empty_for_visits_without_service(sessions_mod):
    c = sessions_mod.upsert_client_visit("+79991110013", "Дана", BRANCH, "М333ММ", 500)
    assert c["service_breakdown"] == []
    assert c["favorite_service"] is None


def test_service_breakdown_empty_for_no_visits_client(sessions_mod):
    sessions_mod.import_contact_car_labels([("+79991110014", "Focus")])
    c = sessions_mod.find_client("+79991110014")
    assert c["service_breakdown"] == []


def test_avg_check_rounds_to_nearest(sessions_mod):
    phone = "+79991110007"
    sessions_mod.upsert_client_visit(phone, "Рита", BRANCH, "Ж777ЖЖ", 500)
    sessions_mod.upsert_client_visit(phone, "Рита", BRANCH, "Ж777ЖЖ", 400)
    sessions_mod.upsert_client_visit(phone, "Рита", BRANCH, "Ж777ЖЖ", 400)
    c = sessions_mod.find_client(phone)
    assert c["avg_check"] == round((500 + 400 + 400) / 3)
