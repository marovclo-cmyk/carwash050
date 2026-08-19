"""
Разовый скрипт миграции: добавляет колонки telegram_id/notify_opt_in в уже
существующую таблицу clients (Stage 21, GAP-NOTIFY1 — фундамент связки
клиента с Telegram-ботом для уведомлений).

Отличается от migrate_clients_to_db.py: тот переносил данные из старого
carwash_clients.json в БД (JSON → таблица); этот — добавляет НОВЫЕ КОЛОНКИ
в уже существующую в БД таблицу clients. db.py's Base.metadata.create_all()
создаёт только отсутствующие ТАБЛИЦЫ целиком и не умеет добавлять колонки
к уже существующей таблице — поэтому для уже развёрнутого прода (Railway
Postgres) нужен именно ALTER TABLE, выполняемый этим скриптом.

Запускать ОДИН РАЗ вручную на деплое, после выкладки кода Stage 21 — с тем
же DATABASE_URL (прод) или DATA_DIR (дев/SQLite), что у самого приложения.

Идемпотентен: перед ALTER TABLE проверяет через инспекцию схемы, есть ли
уже такая колонка — безопасно запускать повторно (в т.ч. на новых базах,
где db.py уже создал таблицу clients сразу с этими колонками — тогда
скрипт просто ничего не делает).

Использование:
    python migrate_add_client_telegram_fields.py
"""
from sqlalchemy import inspect, text

from db import get_engine


def main():
    engine = get_engine()
    inspector = inspect(engine)
    existing_columns = {col["name"] for col in inspector.get_columns("clients")}

    added = []
    with engine.begin() as conn:
        if "telegram_id" not in existing_columns:
            conn.execute(text("ALTER TABLE clients ADD COLUMN telegram_id BIGINT"))
            added.append("telegram_id")
        if "notify_opt_in" not in existing_columns:
            # NOT NULL DEFAULT FALSE — совместимо и с SQLite (дев), и с
            # Postgres (прод); уже существующие строки получат FALSE.
            conn.execute(text(
                "ALTER TABLE clients ADD COLUMN notify_opt_in BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            added.append("notify_opt_in")

    if added:
        print(f"✅ Добавлены колонки в таблицу clients: {', '.join(added)}.")
    else:
        print("✅ Обе колонки (telegram_id, notify_opt_in) уже существуют — миграция не требовалась.")


if __name__ == "__main__":
    main()
