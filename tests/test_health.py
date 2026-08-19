"""
Тест health-check роута (`/health`), добавленного для продовой готовности
Railway — см. PROJECT_BRAIN/RAILWAY_DEPLOYMENT_PLAN.md, пункт
"Open /health if present; otherwise add it before production".

Роут без авторизации, проверяет только что процесс жив и БД отвечает на
простой запрос. Тестовое окружение (`webapp_client`) использует SQLite
через изолированный DATA_DIR — эквивалентная, но не идентичная прод-БД
(Postgres) проверка; сам факт, что оба диалекта проходят через одну и ту
же ветку кода (`db.get_engine()` + `SELECT 1`), достаточен здесь.
"""


def test_health_ok(webapp_client):
    client, _sessions, _server = webapp_client
    r = client.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


def test_health_requires_no_auth(webapp_client):
    """Health-check не должен требовать ни X-Init-Data, ни X-Site-Token —
    иначе платформа деплоя (Railway) не сможет использовать его как
    liveness/readiness-проверку до того, как приложение авторизовано."""
    client, _sessions, _server = webapp_client
    r = client.get("/health")
    assert r.status_code == 200
