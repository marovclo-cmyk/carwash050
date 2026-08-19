"""
Разовый скрипт миграции: добавляет колонку reminder_sent в уже
существующую таблицу bookings (Stage 22, Phase 8 — напоминания о
записи клиенту).

Тот же принцип, что у migrate_add_client_telegram_fields.py (Stage 21):
db.py's Base.metadata.create_all() создаёт только отсутствующие ТАБЛИЦЫ
целиком и не умеет добавлять колонки к уже существующей таблице —
поэтому для уже развёрнутого прода (Railway Postgres) нужен именно
ALTER TABLE, выполняемый этим скриптом.

Запускать ОДИН РАЗ вручную на деплое, после выкладки кода Stage 22 — с
тем же DATABASE_URL (прод) или DATA_DIR (дев/SQLite), что у самого
приложения.

Идемпотентен: перед ALTER TABLE проверяет через инспекцию схемы, есть
ли уже такая колонка — безопасно запускать повторно (в т.ч. на новых
базах, где db.py уже создал таблицу bookings сразу с этой колонкой —
тогда скрипт просто ничего не делает).

Использование:
    python migrate_add_booking_reminder_field.py
"""
from sqlalchemy import inspect, text

from db import get_engine


def main():
    engine = get_engine()
    inspector = inspect(engine)
    existing_columns = {col["name"] for col in inspector.get_columns("bookings")}

    if "reminder_sent" not in existing_columns:
        with engine.begin() as conn:
            # NOT NULL DEFAULT FALSE — совместимо и с SQLite (дев), и с
            # Postgres (прод); уже существующие записи получат FALSE
            # (т.е. считаются "напоминание ещё не отправлено", что
            # безопасно даже для записей в прошлом — job фильтрует их по
            # времени начала и просто их не выберет).
            conn.execute(text(
                "ALTER TABLE bookings ADD COLUMN reminder_sent BOOLEAN NOT NULL DEFAULT FALSE"
            ))
        print("✅ Добавлена колонка в таблицу bookings: reminder_sent.")
    else:
        print("✅ Колонка reminder_sent уже существует — миграция не требовалась.")


if __name__ == "__main__":
    main()
