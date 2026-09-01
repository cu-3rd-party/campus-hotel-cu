import logging

from fastapi import (
    FastAPI,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

import campuses, config, storage
from api import router as api_router
from database import Base, engine, wait_for_db

log = logging.getLogger(__name__)

app = FastAPI(title="Кампус-отели Диск и Облако — поиск соседей", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


def ensure_columns() -> None:
    """Мини-миграция: добавляем новые колонки, не теряя существующие анкеты.

    Alembic не подключён, а create_all не умеет менять уже созданные таблицы.
    """
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS telegram_id BIGINT")
        )
        conn.execute(
            text(
                "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS telegram_verified "
                "BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS group_id INTEGER "
                "REFERENCES groups(id)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT"
            )
        )

        # Кампус-отель. Появился, когда сервис стал обслуживать два отеля.
        # DEFAULT 'disk' переселяет туда всех, кто зарегистрировался раньше:
        # тогда существовал только «Диск», в него они и записывались.
        for table in ("profiles", "groups"):
            conn.execute(
                text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS campus "
                    f"VARCHAR(20) NOT NULL DEFAULT '{campuses.DISK}'"
                )
            )

        # Возраст и курс больше не обязательны — их перестали собирать.
        conn.execute(text("ALTER TABLE profiles ALTER COLUMN age DROP NOT NULL"))

        # Блоки: комната знает, в каком блоке состоит (в «Облаке» — никогда).
        conn.execute(
            text(
                "ALTER TABLE groups ADD COLUMN IF NOT EXISTS block_id INTEGER "
                "REFERENCES blocks(id)"
            )
        )

        # Один желаемый размер комнаты → несколько: «хочу 3 или 4, но не 2».
        # Старое значение переносим как список из одного элемента, NULL
        # («не предпочтительно») превращается в пустую строку — «не важно».
        conn.execute(
            text(
                "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS room_capacities "
                "VARCHAR(20) NOT NULL DEFAULT ''"
            )
        )
        has_room_capacity = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'profiles' AND column_name = 'room_capacity'"
            )
        ).first()
        if has_room_capacity:
            conn.execute(
                text(
                    "UPDATE profiles SET room_capacities = room_capacity::text "
                    "WHERE room_capacity IS NOT NULL AND room_capacities = ''"
                )
            )
            conn.execute(text("ALTER TABLE profiles DROP COLUMN room_capacity"))

        # «О себе» — была в модели, но не в миграции: на базах, где таблица уже
        # существовала до этого поля, любой запрос к анкетам падал с ошибкой
        # "column profiles.bio does not exist".
        conn.execute(
            text(
                "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS bio TEXT NOT NULL DEFAULT ''"
            )
        )

        # Факультет (свободный текст) → направление (5 вариантов).
        conn.execute(
            text("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS track VARCHAR(20)")
        )
        has_faculty = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'profiles' AND column_name = 'faculty'"
            )
        ).first()
        if has_faculty:
            # Переносим старые факультеты по смыслу, остальное — «не определился».
            conn.execute(
                text(
                    """
                    UPDATE profiles SET track = CASE
                        WHEN faculty ILIKE '%дизайн%' THEN 'design'
                        WHEN faculty ILIKE '%информатик%'
                          OR faculty ILIKE '%математик%'
                          OR faculty ILIKE '%программ%' THEN 'dev'
                        WHEN faculty ILIKE '%эконом%'
                          OR faculty ILIKE '%бизнес%'
                          OR faculty ILIKE '%менеджмент%' THEN 'business'
                        WHEN faculty ILIKE '%искусственн%' THEN 'ai'
                        ELSE 'undecided'
                    END
                    WHERE track IS NULL
                    """
                )
            )
            conn.execute(text("ALTER TABLE profiles DROP COLUMN faculty"))
        conn.execute(
            text("UPDATE profiles SET track = 'undecided' WHERE track IS NULL")
        )
        conn.execute(text("ALTER TABLE profiles ALTER COLUMN track SET NOT NULL"))

        # Курс. NULL = «не выбран»; принудительно ставить 1-й нельзя — это
        # враньё в чужой анкете (см. блок «не выбрано» ниже).
        conn.execute(
            text("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS course INTEGER")
        )

        # Новые бытовые поля анкеты.
        for column, default in (
            ("wakeup", "alarm_one"),
            ("cooking", "self"),
            ("guests", "sometimes"),
        ):
            conn.execute(
                text(
                    f"ALTER TABLE profiles ADD COLUMN IF NOT EXISTS {column} "
                    f"VARCHAR(20) NOT NULL DEFAULT '{default}'"
                )
            )
        # Готовка теперь допускает несколько значений через запятую — нужна ширина.
        conn.execute(text("ALTER TABLE profiles ALTER COLUMN cooking TYPE VARCHAR(60)"))

        # Быт по просьбам пользователей: душ, температура, звук, алкоголь, храп.
        # Новые поля добавляем сразу с «не выбрано»: приписывать человеку ответ,
        # которого он не давал, мы больше не хотим (см. блок ниже).
        for column, default in (
            ("shower", "any"),
            ("temperature", "medium"),
            ("noise", ""),
            ("alcohol", "sometimes"),
            ("snoring", ""),
        ):
            conn.execute(
                text(
                    f"ALTER TABLE profiles ADD COLUMN IF NOT EXISTS {column} "
                    f"VARCHAR(20) NOT NULL DEFAULT '{default}'"
                )
            )

        # Звук: «слушаю в наушниках» → «умеренно». Для соседа наушники — та же
        # тишина, и выбор между ними ничего не говорил; полезнее средняя
        # ступень между тишиной и музыкой вслух. Старые ответы переносим, а не
        # обнуляем: человек уже сказал «шуметь не буду», это и есть «умеренно».
        conn.execute(
            text("UPDATE profiles SET noise = 'moderate' WHERE noise = 'headphones'")
        )

        # Чистоплотность (1..5) → аккуратность (relaxed | medium | neat).
        conn.execute(
            text(
                "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS tidiness "
                "VARCHAR(20) NOT NULL DEFAULT 'medium'"
            )
        )
        has_cleanliness = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'profiles' AND column_name = 'cleanliness'"
            )
        ).first()
        if has_cleanliness:
            conn.execute(
                text(
                    """
                    UPDATE profiles SET tidiness = CASE
                        WHEN cleanliness <= 2 THEN 'relaxed'
                        WHEN cleanliness >= 4 THEN 'neat'
                        ELSE 'medium'
                    END
                    """
                )
            )
            conn.execute(text("ALTER TABLE profiles DROP COLUMN cleanliness"))

        # ===== «Не выбрано» вместо выдуманных значений =====
        # Идёт последним: к этому моменту все колонки точно существуют.
        # Курс — исключение: варианта «не выбрано» у него нет, по умолчанию 1-й.
        conn.execute(text("UPDATE profiles SET course = 1 WHERE course IS NULL"))
        conn.execute(text("ALTER TABLE profiles ALTER COLUMN course SET DEFAULT 1"))
        conn.execute(text("ALTER TABLE profiles ALTER COLUMN course SET NOT NULL"))
        # Курсов на бакалавриате всего 4, а раньше в анкете предлагались 5 и 6.
        # Без этого анкеты со старыми значениями перестали бы отдаваться:
        # схема ответа их больше не пропускает, и лента падала бы с ошибкой.
        conn.execute(text("UPDATE profiles SET course = 4 WHERE course > 4"))
        for column in (
            "track",
            "sleep_schedule",
            "smoking",
            "tidiness",
            "wakeup",
            "cooking",
            "guests",
            "shower",
            "temperature",
            "noise",
            "alcohol",
            "snoring",
        ):
            conn.execute(
                text(f"ALTER TABLE profiles ALTER COLUMN {column} SET DEFAULT ''")
            )

        # Одноразовый сброс. Эти поля раньше проставлялись дефолтом всем подряд
        # («один будильник», «готовит сам»…), хотя человек их не выбирал — в
        # чужих анкетах появлялась неправда. Чистим ровно один раз: маркер в
        # schema_meta не даёт затереть уже осознанно заполненные анкеты.
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_meta ("
                "key VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP DEFAULT now())"
            )
        )
        already = conn.execute(
            text("SELECT 1 FROM schema_meta WHERE key = 'reset_fabricated_defaults'")
        ).first()
        if not already:
            conn.execute(
                text(
                    """
                    UPDATE profiles SET
                        wakeup = '',
                        cooking = '',
                        guests = '',
                        shower = '',
                        temperature = '',
                        noise = '',
                        alcohol = ''
                    """
                )
            )
            conn.execute(
                text(
                    "INSERT INTO schema_meta (key) VALUES ('reset_fabricated_defaults')"
                )
            )


@app.on_event("startup")
def on_startup():
    wait_for_db()
    Base.metadata.create_all(bind=engine)
    ensure_columns()
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # Раздаём загруженные фото. Монтируем после старта, когда папка точно есть.
    app.mount(
        storage.PUBLIC_PREFIX,
        StaticFiles(directory=config.UPLOAD_DIR),
        name="media",
    )
    # Состояние ленты — в лог при старте: иначе «почему не приходит» проверяется
    # только созданием анкеты, а это заметно дольше, чем заглянуть в логи.
    if config.FEED_CHAT_ID:
        log.info(
            "Лента новых анкет: чат %s, тема %s",
            config.FEED_CHAT_ID,
            config.FEED_THREAD_ID or "не задана (сообщения уйдут в General)",
        )
    else:
        log.warning("Лента новых анкет выключена: нет TELEGRAM_FEED_CHAT_ID")
