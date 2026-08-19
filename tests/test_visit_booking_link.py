"""
Тесты точной visit→booking связи (GAP-DB1, Stage 23 / Phase 5.1 — item 3
из бандла Phase 4/5, отложенный из Phase 2/3).

До этого прохода client.visits хранили только день/филиал/машину — Client
360 мог связать визит с записью журнала лишь по совпадению даты (см.
PROJECT_STATE.md → Stage 23 / Phase 2). Теперь visits опционально несут
booking_id — точную связь с конкретной записью, проставляемую во всех
write-путях, где машина в кассе создаётся/правится из записи журнала:
1. sessions.upsert_client_visit — сам факт, что поле сохраняется и
   прокидывается через client_summary (тест на уровне sessions.py, без HTTP);
2. _maybe_convert_booking_to_car (авто-конвертация записи в машину) —
   booking_id визита совпадает с id записи;
3. api_edit_car (ручное редактирование машины кассы через PUT
   /api/car/{branch}/{num}) — находит запись-источник по car_num через
   find_booking_by_car_num и проставляет её id.

Визиты без записи (ручное добавление машины, минуя журнал) по-прежнему
не несут booking_id (None) — это не регрессия, а честное отсутствие связи,
как и было заявлено при отложении этого пункта.
"""
from datetime import datetime

from config import BRANCHES, SERVICES

BRANCH = BRANCHES[0]
OWNER_NAME = "Тестовый Владелец"
PASSWORD = "test-password"
TODAY = datetime.now().strftime("%d.%m.%Y")
SERVICE_KEY = next(iter(SERVICES))


def _owner_headers(client) -> dict:
    r = client.post("/api/site/login", json={"password": PASSWORD, "name": OWNER_NAME, "branch": ""})
    assert r.status_code == 200, r.text
    return {"X-Site-Token": r.json()["token"]}


# ── 1. sessions.py — уровень данных, без HTTP ───────────────────────────────

def test_upsert_client_visit_stores_booking_id(sessions_mod):
    client = sessions_mod.upsert_client_visit(
        "+79992220001", "Настя", BRANCH, "О111ОО", 900, booking_id=42,
    )
    assert client["visits"][-1]["booking_id"] == 42


def test_upsert_client_visit_without_booking_id_stays_none(sessions_mod):
    """Обратная совместимость: старые вызовы (и ручное добавление машины
    в кассу мимо журнала) по-прежнему не передают booking_id."""
    client = sessions_mod.upsert_client_visit(
        "+79992220002", "Рома", BRANCH, "П222ПП", 900,
    )
    assert client["visits"][-1]["booking_id"] is None


def test_find_booking_by_car_num(sessions_mod):
    booking = sessions_mod.create_booking(
        BRANCH, TODAY, 1, "10:00", "10:30", price=900, client_name="Клиент",
    )
    sessions_mod.update_booking(booking["id"], car_num=7)
    found = sessions_mod.find_booking_by_car_num(BRANCH, TODAY, 7)
    assert found is not None
    assert found["id"] == booking["id"]


def test_find_booking_by_car_num_no_match(sessions_mod):
    assert sessions_mod.find_booking_by_car_num(BRANCH, TODAY, 999) is None


# ── 2. авто-конвертация записи в машину (_maybe_convert_booking_to_car) ────

def test_booking_conversion_sets_booking_id_on_visit(webapp_client):
    client, sessions_module, _server = webapp_client
    headers = _owner_headers(client)
    client.post("/api/openday", params={"branch": BRANCH}, headers=headers)

    r = client.post("/api/bookings", json={
        "branch": BRANCH, "date": TODAY, "box": 1,
        "start_time": "10:00", "end_time": "11:00",
        "employee": "Иван Тестов", "body_type": "sedan",
        "car": "Р333РР", "service_keys": [SERVICE_KEY], "custom_services": [],
        "product_keys": [], "payment": "нал", "comment": "",
        "phone": "+79992220003", "client_name": "Клиент Связка", "status": "waiting",
    }, headers=headers)
    assert r.status_code == 200, r.text
    booking = r.json()["booking"]
    assert booking.get("car_num"), "запись с услугами должна авто-сконвертироваться в машину"

    c = sessions_module.find_client("+79992220003")
    assert c is not None
    assert c["visits"][-1]["booking_id"] == booking["id"]


# ── 3. ручное редактирование машины (api_edit_car → find_booking_by_car_num) ─

def test_manual_car_edit_links_to_source_booking(webapp_client):
    client, sessions_module, _server = webapp_client
    headers = _owner_headers(client)
    client.post("/api/openday", params={"branch": BRANCH}, headers=headers)

    # запись без телефона -> конвертируется в машину без визита клиента
    r = client.post("/api/bookings", json={
        "branch": BRANCH, "date": TODAY, "box": 1,
        "start_time": "12:00", "end_time": "13:00",
        "employee": "Иван Тестов", "body_type": "sedan",
        "car": "С444СС", "service_keys": [SERVICE_KEY], "custom_services": [],
        "product_keys": [], "payment": "нал", "comment": "",
        "phone": "", "client_name": "", "status": "waiting",
    }, headers=headers)
    assert r.status_code == 200, r.text
    booking = r.json()["booking"]
    car_num = booking["car_num"]
    assert car_num

    # телефон проставляется позже, напрямую правкой машины в кассе (не записи) —
    # это и есть путь api_edit_car, для которого нужен find_booking_by_car_num
    r2 = client.put(f"/api/car/{BRANCH}/{car_num}", json={
        "phone": "+79992220004", "client_name": "Клиент Из Кассы",
    }, headers=headers)
    assert r2.status_code == 200, r2.text

    c = sessions_module.find_client("+79992220004")
    assert c is not None
    assert c["visits"][-1]["booking_id"] == booking["id"]


def test_manual_car_edit_without_source_booking_leaves_none(webapp_client):
    """Машина, добавленная напрямую (не из записи) — find_booking_by_car_num
    ничего не находит, визит клиента честно без booking_id."""
    client, sessions_module, _server = webapp_client
    headers = _owner_headers(client)
    client.post("/api/openday", params={"branch": BRANCH}, headers=headers)

    r = client.post("/api/car", json={
        "branch": BRANCH, "employee": "Иван", "body_type": "sedan",
        "service_keys": [], "custom_services": [{"name": "Тест", "price": 900, "percent": 0}],
        "payment": "нал", "car": "Т555ТТ",
    }, headers=headers)
    assert r.status_code == 200, r.text
    car_num = r.json()["car"]["num"]

    r2 = client.put(f"/api/car/{BRANCH}/{car_num}", json={
        "phone": "+79992220005", "client_name": "Клиент Без Записи",
    }, headers=headers)
    assert r2.status_code == 200, r2.text

    c = sessions_module.find_client("+79992220005")
    assert c is not None
    assert c["visits"][-1]["booking_id"] is None
