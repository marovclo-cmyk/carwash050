"""
HTTP-уровень уведомлений (Stage 24, Phase 6):
- GET/PUT /api/notification-settings, GET /api/notification-log — доступ
  только владельцу (require_owner, как /api/users);
- shift_open/shift_close/new_booking действительно пишут строку в
  NotificationLog при срабатывании через реальные роуты
  (/api/openday, /api/newday, /api/public/booking), с учётом настроек
  вкл/выкл.

Сама отправка в Telegram использует синтаксически валидный, но нерабочий
тестовый токен (см. webapp_client в conftest.py) — notify_user/job'ы уже
рассчитаны на "не удалось отправить, тихо логируем" (см. notify.py),
поэтому запись в лог появляется независимо от результата доставки.
"""
from config import BRANCHES

BRANCH = BRANCHES[0]
OWNER_NAME = "Тестовый Владелец"
PASSWORD = "test-password"


def _owner_headers(client) -> dict:
    r = client.post("/api/site/login", json={"password": PASSWORD, "name": OWNER_NAME, "branch": ""})
    assert r.status_code == 200, r.text
    return {"X-Site-Token": r.json()["token"]}


def _worker_headers(client, sessions_mod) -> dict:
    sessions_mod.add_branch_worker(BRANCH, "Иван Мойщиков")
    r = client.post("/api/site/login", json={"password": PASSWORD, "name": "Иван Мойщиков", "branch": BRANCH})
    assert r.status_code == 200, r.text
    return {"X-Site-Token": r.json()["token"]}


# ── доступ ───────────────────────────────────────────────────────────────

def test_notification_settings_requires_owner(webapp_client):
    client, sessions_mod, _server = webapp_client
    headers = _worker_headers(client, sessions_mod)

    r = client.get("/api/notification-settings", headers=headers)
    assert r.status_code == 403


def test_notification_log_requires_owner(webapp_client):
    client, sessions_mod, _server = webapp_client
    headers = _worker_headers(client, sessions_mod)

    r = client.get("/api/notification-log", headers=headers)
    assert r.status_code == 403


def test_notification_settings_rejects_unauthenticated(webapp_client):
    client, _sessions, _server = webapp_client
    r = client.get("/api/notification-settings")
    assert r.status_code == 403


# ── настройки ────────────────────────────────────────────────────────────

def test_get_notification_settings_defaults(webapp_client):
    client, _sessions, _server = webapp_client
    headers = _owner_headers(client)

    r = client.get("/api/notification-settings", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["booking_reminders_enabled"] is True
    assert data["reminder_window_minutes"] == 60


def test_put_notification_settings_partial_update(webapp_client):
    client, _sessions, _server = webapp_client
    headers = _owner_headers(client)

    r = client.put("/api/notification-settings", headers=headers,
                    json={"winback_enabled": False, "winback_cooldown_days": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["winback_enabled"] is False
    assert data["winback_cooldown_days"] == 10
    assert data["booking_reminders_enabled"] is True  # не тронуто

    r2 = client.get("/api/notification-settings", headers=headers)
    assert r2.json()["winback_cooldown_days"] == 10


def test_put_notification_settings_rejects_non_positive_window(webapp_client):
    client, _sessions, _server = webapp_client
    headers = _owner_headers(client)

    r = client.put("/api/notification-settings", headers=headers, json={"reminder_window_minutes": 0})
    assert r.status_code == 400

    r2 = client.put("/api/notification-settings", headers=headers, json={"winback_cooldown_days": -5})
    assert r2.status_code == 400


# ── shift_open / shift_close пишут в лог ───────────────────────────────────

def test_openday_logs_shift_open_notification(webapp_client):
    client, _sessions, _server = webapp_client
    headers = _owner_headers(client)

    r = client.post("/api/openday", params={"branch": BRANCH}, headers=headers)
    assert r.status_code == 200

    log = client.get("/api/notification-log", params={"kind": "shift_open"}, headers=headers).json()["entries"]
    assert len(log) == 1
    assert log[0]["branch"] == BRANCH


def test_openday_does_not_log_when_shift_notifications_disabled(webapp_client):
    client, _sessions, _server = webapp_client
    headers = _owner_headers(client)
    client.put("/api/notification-settings", headers=headers, json={"shift_notifications_enabled": False})

    client.post("/api/openday", params={"branch": BRANCH}, headers=headers)

    log = client.get("/api/notification-log", params={"kind": "shift_open"}, headers=headers).json()["entries"]
    assert log == []


def test_newday_logs_shift_close_notification(webapp_client):
    client, _sessions, _server = webapp_client
    headers = _owner_headers(client)
    client.post("/api/openday", params={"branch": BRANCH}, headers=headers)

    r = client.post("/api/newday", params={"branch": BRANCH}, headers=headers, json={})
    assert r.status_code == 200

    log = client.get("/api/notification-log", params={"kind": "shift_close"}, headers=headers).json()["entries"]
    assert len(log) == 1


# ── new_booking пишет в лог (только публичная запись клиентом) ────────────

def test_public_booking_logs_new_booking_notification(webapp_client):
    client, sessions_mod, _server = webapp_client
    headers = _owner_headers(client)
    sessions_mod.set_branch_admin(BRANCH, 555111)
    sessions_mod.add_branch_box(BRANCH, "Бокс 1")

    slots = client.get("/api/public/slots", params={"branch": BRANCH, "date": "01.01.2099", "body_type": "sedan"})
    assert slots.status_code == 200, slots.text
    available = slots.json().get("slots") or []
    assert available, "нет свободных слотов для теста — проверь /api/public/slots"

    r = client.post("/api/public/booking", json={
        "branch": BRANCH, "date": "01.01.2099", "start_time": available[0],
        "body_type": "sedan", "service_keys": [], "phone": "+79991234567",
        "client_name": "Клиент Публичный",
    })
    assert r.status_code == 200, r.text

    log = client.get("/api/notification-log", params={"kind": "new_booking"}, headers=headers).json()["entries"]
    assert len(log) == 2  # админ филиала + владелец
    assert {e["recipient_label"] for e in log} == {f"Админ филиала «{BRANCH}»", "Владелец"}


def test_manual_booking_via_crm_does_not_log_new_booking(webapp_client):
    """Записи, которые сотрудник создаёт сам в CRM (/api/bookings), не
    должны спамить его же собственными уведомлениями — только самозапись
    клиента через /api/public/booking."""
    client, sessions_mod, _server = webapp_client
    headers = _owner_headers(client)

    r = client.post("/api/bookings", headers=headers, json={
        "branch": BRANCH, "date": "01.01.2099", "box": 1,
        "start_time": "10:00", "end_time": "11:00",
        "employee": "Иван Тестов", "body_type": "sedan",
        "car": "А111АА", "service_keys": [], "custom_services": [],
        "product_keys": [], "payment": "нал", "comment": "",
        "phone": "", "client_name": "Клиент Тестов", "status": "waiting",
    })
    assert r.status_code == 200, r.text

    log = client.get("/api/notification-log", params={"kind": "new_booking"}, headers=headers).json()["entries"]
    assert log == []
