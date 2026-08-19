"""
Разовый скрипт миграции: добавляет колонку last_winback_sent_at в уже
существующую таблицу clients (Stage 23, Phase 8 — win-back для
неактивных клиентов).

Тот же принцип, что у migrate_add_client_telegram_fields.py (Stage 21) и
migrate_add_booking_reminder_field.py (Stage 22): db.py's
Base.metadata.create_all() создаёт только отсутствующие ТАБЛИЦЫ целиком
и не умеет добавлять колонки к уже существующей таблице — поэтому для
уже развёрнутого прода (Railway Postgres) нужен именно ALTER TABLE,
выполняемый этим скриптом.

Запускать ОДИН РАЗ вручную на деплое, после выкладки кода Stage 23 — с
тем же DATABASE_URL (прод) или DATA_DIR (дев/SQLite), что у самого
приложения.

Идемпотентен: перед ALTER TABLE проверяет через инспекцию схемы, есть
ли уже такая колонка — безопасно запускать повторно (в т.ч. на новых
базах, где db.py уже создал таблицу clients сразу с этой колонкой —
тогда скрипт просто ничего не делает).

Использование:
    python migrate_add_client_winback_field.py
"""
from sqlalchemy import inspect, text

from db import get_engine


def main():
    engine = get_engine()
    inspector = inspect(engine)
    existing_columns = {col["name"] for col in inspector.get_columns("clients")}

    if "last_winback_sent_at" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE clients ADD COLUMN last_winback_sent_at VARCHAR"
            ))
        print("✅ Добавлена колонка в таблицу clients: last_winback_sent_at.")
    else:
        print("✅ Колонка last_winback_sent_at уже существует — миграция не требовалась.")


if __name__ == "__main__":
    main()
