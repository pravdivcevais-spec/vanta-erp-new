"""
db.py — всё взаимодействие с базой данных:
  - подключение (get_engine, check_database_connection)
  - загрузчики данных (load_*)
  - мутации (create_*, update_*, finish_*, assign_*, issue_*, consume_* и т.д.)
"""

import json
import re as _re
import time
from datetime import date, datetime

import psycopg2
import streamlit as st

from utils import (
    normalize_gov_number,
    normalize_iot_device_id,
    validate_gov_format,
    validate_iot_format,
)


# ===========================================================================
# ТОНКАЯ ОБЁРТКА — прямой psycopg2 вместо SQLAlchemy engine
# Решает: "server closed the connection unexpectedly [SQL: show standard_conforming_strings]"
# SQLAlchemy запускает этот запрос при инициализации диалекта; psycopg2 напрямую — нет.
# ===========================================================================

# Регулярное выражение: :param_name → %(param_name)s
# (?<!:) — не матчим :: (оператор приведения типов PostgreSQL)
_NAMED_PARAM_RE = _re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")


class _TextClause:
    """Минимальная замена sqlalchemy.text() — хранит SQL-строку."""
    __slots__ = ("text",)

    def __init__(self, sql: str) -> None:
        self.text = sql


def text(sql: str) -> _TextClause:
    """Обёртка для SQL-строк, совместимая со старым кодом."""
    return _TextClause(sql)


class _Row(dict):
    """Строка результата с доступом по атрибуту и по ключу."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


class _MappingResult:
    __slots__ = ("_rows",)

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    """Результат запроса — поддерживает mappings(), scalar_one(), fetchall()."""

    def __init__(self, cursor) -> None:
        if cursor.description:
            cols = [d[0] for d in cursor.description]
            raw = cursor.fetchall()
            self._rows: list[_Row] = [_Row(zip(cols, r)) for r in raw]
            # tuples для fetchall() с доступом через row[0]
            self._tuples: list[tuple] = [tuple(r) for r in raw]
        else:
            self._rows = []
            self._tuples = []

    def mappings(self) -> _MappingResult:
        return _MappingResult(self._rows)

    def scalar_one(self):
        if not self._rows:
            raise ValueError("Нет строк в результате запроса.")
        return next(iter(self._rows[0].values()))

    def scalar_one_or_none(self):
        if not self._rows:
            return None
        return next(iter(self._rows[0].values()))

    def fetchall(self) -> list[tuple]:
        """Возвращает список кортежей — совместимо с row[0]."""
        return self._tuples

    def first(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _PsycopgConn:
    """Контекстный менеджер для одного psycopg2-соединения."""

    def __init__(self, dsn: str, begin: bool = False) -> None:
        self._dsn = dsn
        self._begin = begin
        self._conn = None

    def __enter__(self):
        self._conn = psycopg2.connect(
            self._dsn,
            connect_timeout=15,
            sslmode="require",
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=3,
        )
        if not self._begin:
            self._conn.autocommit = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._begin:
            if exc_type:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
            else:
                self._conn.commit()
        try:
            self._conn.close()
        except Exception:
            pass

    def execute(self, stmt, params=None) -> _Result:
        sql = stmt.text if hasattr(stmt, "text") else str(stmt)
        sql = _NAMED_PARAM_RE.sub(r"%(\1)s", sql)
        cur = self._conn.cursor()
        cur.execute(sql, params if params else None)
        return _Result(cur)


class _PsycopgEngine:
    """Минимальный аналог SQLAlchemy engine на базе прямого psycopg2."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def connect(self) -> _PsycopgConn:
        """Соединение для чтения (autocommit=True)."""
        return _PsycopgConn(self._dsn, begin=False)

    def begin(self) -> _PsycopgConn:
        """Соединение с транзакцией: commit при выходе, rollback при ошибке."""
        return _PsycopgConn(self._dsn, begin=True)


# ===========================================================================
# ПОДКЛЮЧЕНИЕ
# ===========================================================================

@st.cache_resource
def get_engine() -> _PsycopgEngine:
    dsn = st.secrets["DATABASE_URL"]
    return _PsycopgEngine(dsn)


def check_database_connection(engine, attempts: int = 2) -> tuple[bool, str | None]:
    last_error = None
    for _ in range(attempts):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True, None
        except psycopg2.Error as exc:
            last_error = str(exc)
        except Exception as exc:
            last_error = str(exc)
    return False, last_error


def _safe_migrate(engine, sql: str) -> None:
    """Выполняет одну DDL-команду в отдельной транзакции; ошибки игнорирует."""
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
    except Exception:
        pass


def ensure_rental_company_schema(engine) -> None:
    """Добавляет недостающие колонки в rental и incoming_request."""
    with engine.begin() as conn:
        # --- rental: company_id ---
        company_exists = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_name = 'rental' AND column_name = 'company_id'
                """
            )
        ).scalar_one()
        if not company_exists:
            conn.execute(text("ALTER TABLE rental ADD COLUMN company_id bigint NULL"))
            conn.execute(
                text(
                    """
                    ALTER TABLE rental
                    ADD CONSTRAINT fk_rental_company
                    FOREIGN KEY (company_id) REFERENCES company(id) ON DELETE RESTRICT
                    """
                )
            )

        client_nullable = conn.execute(
            text(
                """
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_name = 'rental' AND column_name = 'client_id'
                """
            )
        ).scalar_one()
        if client_nullable == "NO":
            conn.execute(text("ALTER TABLE rental ALTER COLUMN client_id DROP NOT NULL"))

        # --- incoming_request: поля для интеграции с M4 ---
        for col, definition in [
            ("source",      "VARCHAR(20) NOT NULL DEFAULT 'vanta'"),
            ("external_id", "VARCHAR(100) NULL"),
            ("deadline",    "TIMESTAMP NULL"),
            ("priority",    "VARCHAR(50) NULL"),
        ]:
            exists = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_name = 'incoming_request' AND column_name = :col
                    """
                ),
                {"col": col},
            ).scalar_one()
            if not exists:
                conn.execute(
                    text(f"ALTER TABLE incoming_request ADD COLUMN {col} {definition}")
                )

        # --- logistics_request ---
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS logistics_request (
                id           SERIAL PRIMARY KEY,
                request_type VARCHAR(20)  NOT NULL,
                darkstore_id INTEGER      REFERENCES darkstore(id) ON DELETE SET NULL,
                status       VARCHAR(50)  NOT NULL DEFAULT 'новая',
                assigned_to  INTEGER      REFERENCES employee(id)  ON DELETE SET NULL,
                created_by   INTEGER      REFERENCES employee(id)  ON DELETE SET NULL,
                notes        TEXT,
                created_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
                updated_at   TIMESTAMP    NOT NULL DEFAULT NOW()
            )
        """))

        # --- logistics_bike ---
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS logistics_bike (
                id             SERIAL  PRIMARY KEY,
                logistics_id   INTEGER NOT NULL REFERENCES logistics_request(id) ON DELETE CASCADE,
                bike_id        INTEGER NOT NULL REFERENCES bike(id) ON DELETE CASCADE,
                UNIQUE (logistics_id, bike_id)
            )
        """))
    # --- Отдельные миграции в независимых транзакциях ---
    _safe_migrate(engine, "ALTER TABLE logistics_bike ADD COLUMN IF NOT EXISTS direction TEXT")
    _safe_migrate(engine, "ALTER TABLE darkstore ADD COLUMN IF NOT EXISTS address TEXT")
    _safe_migrate(engine, "ALTER TABLE spare_part_catalog ADD COLUMN IF NOT EXISTS price INTEGER DEFAULT 0")
    _safe_migrate(engine, "ALTER TABLE repair_request ADD COLUMN IF NOT EXISTS rework_count INTEGER NOT NULL DEFAULT 0")
    _safe_migrate(engine, "ALTER TABLE repair_request DROP CONSTRAINT IF EXISTS repair_request_status_check")
    _safe_migrate(engine, """
        ALTER TABLE repair_request ADD CONSTRAINT repair_request_status_check
        CHECK (status::text = ANY(ARRAY[
            'назначена', 'в работе', 'ожидает запчасти', 'отложена',
            'завершена', 'отменена', 'замена_вело', 'утилизация', 'на проверке'
        ]::text[]))
    """)


def refresh_all_caches() -> None:
    st.cache_data.clear()


# ===========================================================================
# ЗАГРУЗЧИКИ ДАННЫХ (кешируются 60 секунд)
# ===========================================================================

@st.cache_data(ttl=60)
def load_darkstores(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, name, COALESCE(address, '') AS address, direction, latitude, longitude, company_id FROM darkstore ORDER BY name")
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_employees(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, first_name, last_name, role FROM employee ORDER BY role, last_name, first_name")
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_clients(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, type, name, phone, darkstore_id FROM client ORDER BY type, name")
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_companies(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, name, type, created_at FROM company ORDER BY name")
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_rentals(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    r.id, r.bike_id, r.client_id, r.company_id,
                    r.start_dt, r.end_dt, r.days_count, r.status,
                    r.created_at, r.updated_at,
                    c.name  AS client_name,
                    c.type  AS client_type,
                    c.darkstore_id AS client_darkstore_id,
                    co.name AS company_name,
                    co.type AS company_type,
                    b.serial_number, b.gov_number, b.darkstore_id,
                    ds.name AS darkstore_name,
                    ds.direction AS darkstore_direction
                FROM rental r
                LEFT JOIN client  c  ON c.id  = r.client_id
                LEFT JOIN company co ON co.id = r.company_id
                LEFT JOIN bike    b  ON b.id  = r.bike_id
                LEFT JOIN darkstore ds ON ds.id = b.darkstore_id
                ORDER BY r.created_at DESC, r.id DESC
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_bikes(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    b.id, b.serial_number, b.gov_number, b.model,
                    b.location_status, b.tech_status, b.holder_type, b.holder_id,
                    b.darkstore_id, b.days_in_rent, b.iot_device_id,
                    ds.name AS darkstore_name,
                    ds.direction AS darkstore_direction
                FROM bike b
                LEFT JOIN darkstore ds ON ds.id = b.darkstore_id
                ORDER BY b.id
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_incoming_request(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    ir.id, ir.request_type, ir.device_type, ir.direction,
                    ir.darkstore_id, ir.bike_id, ir.problem, ir.status,
                    ir.curator_name, ir.full_address, ir.created_at, ir.updated_at,
                    b.serial_number, b.gov_number, b.model, b.iot_device_id,
                    b.tech_status, b.location_status,
                    ds.name AS darkstore_name,
                    ds.direction AS darkstore_direction,
                    la.assigned_to,
                    e.first_name AS assigned_first_name,
                    e.last_name  AS assigned_last_name,
                    rr.rr_id,
                    rr.rr_client_rating
                FROM incoming_request ir
                LEFT JOIN bike      b  ON b.id  = ir.bike_id
                LEFT JOIN darkstore ds ON ds.id = ir.darkstore_id
                LEFT JOIN LATERAL (
                    SELECT id AS rr_id, client_rating AS rr_client_rating
                    FROM repair_request
                    WHERE incoming_id = ir.id
                    ORDER BY id DESC LIMIT 1
                ) rr ON true
                LEFT JOIN LATERAL (
                    SELECT assigned_to
                    FROM master_assignment
                    WHERE repair_request_id = rr.rr_id
                    ORDER BY assigned_at DESC, id DESC LIMIT 1
                ) la ON true
                LEFT JOIN employee e ON e.id = la.assigned_to
                ORDER BY ir.created_at DESC, ir.id DESC
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_repairs(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                WITH latest_assignment AS (
                    SELECT DISTINCT ON (repair_request_id)
                        repair_request_id, assigned_to, assigned_by, comment, assigned_at
                    FROM master_assignment
                    ORDER BY repair_request_id, assigned_at DESC, id DESC
                )
                SELECT
                    rr.id, rr.bike_id, rr.incoming_id, rr.status, rr.type,
                    rr.postponed_reason, rr.client_rating, rr.client_comment,
                    rr.comment, rr.created_at, rr.updated_at,
                    ir.problem, ir.device_type, ir.request_type, ir.darkstore_id,
                    ir.full_address,
                    b.serial_number, b.gov_number, b.model, b.iot_device_id,
                    b.tech_status, b.location_status, b.holder_type,
                    ds.name AS darkstore_name,
                    ds.direction AS darkstore_direction,
                    ds.latitude AS darkstore_latitude,
                    ds.longitude AS darkstore_longitude,
                    la.assigned_to, la.comment AS assignment_comment, la.assigned_at,
                    e.first_name, e.last_name,
                    e.role AS employee_role
                FROM repair_request rr
                LEFT JOIN incoming_request ir ON ir.id = rr.incoming_id
                LEFT JOIN bike   b  ON b.id  = rr.bike_id
                LEFT JOIN darkstore ds ON ds.id = COALESCE(ir.darkstore_id, b.darkstore_id)
                LEFT JOIN latest_assignment la ON la.repair_request_id = rr.id
                LEFT JOIN employee e ON e.id = la.assigned_to
                ORDER BY rr.updated_at DESC, rr.id DESC
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_bike_logs(_engine):
    try:
        with _engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT bl.*, e.first_name, e.last_name
                    FROM bike_log bl
                    LEFT JOIN employee e ON e.id = bl.actor_id
                    ORDER BY bl.created_at DESC, bl.id DESC
                    """
                )
            ).mappings().all()
        return [dict(row) for row in rows]
    except Exception:
        return []


@st.cache_data(ttl=60)
def load_spare_stock(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    sps.id, sps.spare_part_catalog_id, sps.darkstore_id,
                    sps.quantity, sps.updated_at,
                    spc.article, spc.name AS spare_name,
                    ds.name AS darkstore_name
                FROM spare_part_stock sps
                LEFT JOIN spare_part_catalog spc ON spc.id = sps.spare_part_catalog_id
                LEFT JOIN darkstore ds ON ds.id = sps.darkstore_id
                ORDER BY ds.name, spc.name
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_spare_catalog(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, article, name, description, COALESCE(price, 0) AS price FROM spare_part_catalog ORDER BY name")
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_parts_used(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    rpu.id, rpu.repair_request_id, rpu.spare_part_catalog_id,
                    rpu.quantity_used, rpu.created_at,
                    spc.article, spc.name AS spare_name,
                    rr.type AS repair_type, rr.status AS repair_status,
                    rr.bike_id, rr.incoming_id
                FROM repair_parts_used rpu
                LEFT JOIN spare_part_catalog spc ON spc.id = rpu.spare_part_catalog_id
                LEFT JOIN repair_request rr ON rr.id = rpu.repair_request_id
                ORDER BY rpu.created_at DESC, rpu.id DESC
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_work_types(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, name, default_spare_parts FROM work_type ORDER BY name")
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_master_spare_stock(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    mss.id, mss.master_id, mss.spare_part_catalog_id,
                    mss.quantity, mss.picked_at, mss.updated_at,
                    spc.article, spc.name AS spare_name,
                    e.first_name, e.last_name
                FROM master_spare_stock mss
                LEFT JOIN spare_part_catalog spc ON spc.id = mss.spare_part_catalog_id
                LEFT JOIN employee e ON e.id = mss.master_id
                ORDER BY e.last_name, e.first_name, spc.name
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_productivity(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                WITH latest_assignment AS (
                    SELECT DISTINCT ON (repair_request_id)
                        repair_request_id, assigned_to
                    FROM master_assignment
                    ORDER BY repair_request_id, assigned_at DESC, id DESC
                ),
                daily AS (
                    SELECT
                        la.assigned_to AS employee_id,
                        DATE(rr.updated_at) AS work_day,
                        COUNT(*) AS repairs_done
                    FROM repair_request rr
                    JOIN latest_assignment la ON la.repair_request_id = rr.id
                    WHERE rr.status = 'завершена'
                    GROUP BY la.assigned_to, DATE(rr.updated_at)
                )
                SELECT
                    e.id, e.first_name, e.last_name, e.role,
                    COALESCE(AVG(d.repairs_done), 0) AS avg_repairs_per_day,
                    COALESCE(SUM(d.repairs_done), 0) AS total_repairs,
                    COALESCE(COUNT(d.work_day), 0)   AS shift_days
                FROM employee e
                LEFT JOIN daily d ON d.employee_id = e.id
                GROUP BY e.id, e.first_name, e.last_name, e.role
                ORDER BY e.role, e.last_name, e.first_name
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_logistics(_engine):
    """Загружает logistics_request + список bike_id для каждой заявки."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    lr.id, lr.request_type, lr.status, lr.notes,
                    lr.created_at, lr.updated_at,
                    lr.darkstore_id, ds.name AS darkstore_name,
                    lr.assigned_to, e.first_name AS master_first_name, e.last_name AS master_last_name,
                    lr.created_by
                FROM logistics_request lr
                LEFT JOIN darkstore ds ON ds.id = lr.darkstore_id
                LEFT JOIN employee  e  ON e.id  = lr.assigned_to
                ORDER BY lr.created_at DESC
                """
            )
        ).mappings().all()

        # Загружаем все bike_id привязки одним запросом
        try:
            bike_rows = conn.execute(
                text("SELECT logistics_id, bike_id, direction FROM logistics_bike")
            ).mappings().all()
        except Exception:
            # Колонка direction ещё не добавлена — fallback без неё
            bike_rows_raw = conn.execute(
                text("SELECT logistics_id, bike_id FROM logistics_bike")
            ).mappings().all()
            bike_rows = [dict(r, direction=None) for r in bike_rows_raw]

    bike_map: dict[int, list[int]] = {}
    vyvoz_map: dict[int, list[int]] = {}
    postavka_map: dict[int, list[int]] = {}
    for br in bike_rows:
        lid = br["logistics_id"]
        bid = br["bike_id"]
        direction = br.get("direction")
        bike_map.setdefault(lid, []).append(bid)
        if direction == "вывоз":
            vyvoz_map.setdefault(lid, []).append(bid)
        elif direction == "поставка":
            postavka_map.setdefault(lid, []).append(bid)

    result = []
    for row in rows:
        d = dict(row)
        lid = row["id"]
        d["bike_ids"] = bike_map.get(lid, [])
        d["vyvoz_bike_ids"] = vyvoz_map.get(lid, [])
        d["postavka_bike_ids"] = postavka_map.get(lid, [])
        result.append(d)
    return result


@st.cache_data(ttl=300, show_spinner=False)
def load_all_data(_engine) -> dict:
    """
    Загружает ВСЕ данные в ОДНОМ соединении.
    Кешируется 90 секунд. Сбрасывается через refresh_all_caches().
    До 3 попыток при обрыве соединения.
    """
    last_exc = None
    for _attempt in range(2):
        try:
            return _load_all_data_once(_engine)
        except Exception as exc:
            import traceback
            last_exc = Exception(
                f"Attempt {_attempt + 1}/2 failed: {exc}\n{traceback.format_exc()}"
            )
    raise last_exc


def _load_all_data_once(_engine) -> dict:
    """
    Одно psycopg2-соединение на все запросы.
    Если соединение обрывается — переподключается и повторяет запрос один раз.
    """
    dsn = _engine._dsn

    def _make_conn():
        c = psycopg2.connect(dsn, connect_timeout=8)
        c.autocommit = True
        return c

    _conn = _make_conn()

    def q(sql):
        nonlocal _conn
        for _try in range(2):
            try:
                cur = _conn.cursor()
                cur.execute(sql)
                if cur.description:
                    cols = [d[0] for d in cur.description]
                    return [dict(zip(cols, row)) for row in cur.fetchall()]
                return []
            except psycopg2.OperationalError:
                if _try == 0:
                    try:
                        _conn.close()
                    except Exception:
                        pass
                    _conn = _make_conn()
                else:
                    raise

    darkstores = q("""
        SELECT id, name, COALESCE(address,'') AS address,
               direction, latitude, longitude, company_id
        FROM darkstore ORDER BY name
    """)

    employees = q("""
        SELECT id, first_name, last_name, role
        FROM employee ORDER BY role, last_name, first_name
    """)

    clients = q("SELECT id, type, name, phone, darkstore_id FROM client ORDER BY type, name")
    companies = q("SELECT id, name, type, created_at FROM company ORDER BY name")

    rentals = q("""
        SELECT r.id, r.bike_id, r.client_id, r.company_id,
               r.start_dt, r.end_dt, r.days_count, r.status,
               r.created_at, r.updated_at,
               c.name AS client_name, c.type AS client_type,
               c.darkstore_id AS client_darkstore_id,
               co.name AS company_name, co.type AS company_type,
               b.serial_number, b.gov_number, b.darkstore_id,
               ds.name AS darkstore_name, ds.direction AS darkstore_direction
        FROM rental r
        LEFT JOIN client  c  ON c.id  = r.client_id
        LEFT JOIN company co ON co.id = r.company_id
        LEFT JOIN bike    b  ON b.id  = r.bike_id
        LEFT JOIN darkstore ds ON ds.id = b.darkstore_id
        ORDER BY r.created_at DESC, r.id DESC
    """)

    bikes = q("""
        SELECT b.id, b.serial_number, b.gov_number, b.model,
               b.location_status, b.tech_status, b.holder_type, b.holder_id,
               b.darkstore_id, b.days_in_rent, b.iot_device_id,
               ds.name AS darkstore_name, ds.direction AS darkstore_direction
        FROM bike b
        LEFT JOIN darkstore ds ON ds.id = b.darkstore_id
        ORDER BY b.id
    """)

    incoming_request = q("""
        SELECT ir.id, ir.request_type, ir.device_type, ir.direction,
               ir.darkstore_id, ir.bike_id, ir.problem, ir.status,
               ir.curator_name, ir.full_address, ir.created_at, ir.updated_at,
               b.serial_number, b.gov_number, b.model, b.iot_device_id,
               b.tech_status, b.location_status,
               ds.name AS darkstore_name, ds.direction AS darkstore_direction,
               la.assigned_to,
               e.first_name AS assigned_first_name, e.last_name AS assigned_last_name,
               rr.rr_id, rr.rr_client_rating
        FROM incoming_request ir
        LEFT JOIN bike b ON b.id = ir.bike_id
        LEFT JOIN darkstore ds ON ds.id = ir.darkstore_id
        LEFT JOIN LATERAL (
            SELECT id AS rr_id, client_rating AS rr_client_rating
            FROM repair_request WHERE incoming_id = ir.id
            ORDER BY id DESC LIMIT 1
        ) rr ON true
        LEFT JOIN LATERAL (
            SELECT assigned_to FROM master_assignment
            WHERE repair_request_id = rr.rr_id
            ORDER BY assigned_at DESC, id DESC LIMIT 1
        ) la ON true
        LEFT JOIN employee e ON e.id = la.assigned_to
        ORDER BY ir.created_at DESC, ir.id DESC
    """)

    repairs = q("""
        WITH latest_assignment AS (
            SELECT DISTINCT ON (repair_request_id)
                repair_request_id, assigned_to, assigned_by, comment, assigned_at
            FROM master_assignment
            ORDER BY repair_request_id, assigned_at DESC, id DESC
        )
        SELECT rr.id, rr.bike_id, rr.incoming_id, rr.status, rr.type,
               rr.postponed_reason, rr.client_rating, rr.client_comment,
               rr.comment, rr.created_at, rr.updated_at,
               ir.problem, ir.device_type, ir.request_type, ir.darkstore_id,
               ir.full_address,
               b.serial_number, b.gov_number, b.model, b.iot_device_id,
               b.tech_status, b.location_status, b.holder_type,
               ds.name AS darkstore_name, ds.direction AS darkstore_direction,
               ds.latitude AS darkstore_latitude, ds.longitude AS darkstore_longitude,
               la.assigned_to, la.comment AS assignment_comment, la.assigned_at,
               e.first_name, e.last_name, e.role AS employee_role
        FROM repair_request rr
        LEFT JOIN incoming_request ir ON ir.id = rr.incoming_id
        LEFT JOIN bike b ON b.id = rr.bike_id
        LEFT JOIN darkstore ds ON ds.id = COALESCE(ir.darkstore_id, b.darkstore_id)
        LEFT JOIN latest_assignment la ON la.repair_request_id = rr.id
        LEFT JOIN employee e ON e.id = la.assigned_to
        ORDER BY rr.updated_at DESC, rr.id DESC
    """)

    try:
        bike_logs = q("""
            SELECT bl.*, e.first_name, e.last_name
            FROM bike_log bl
            LEFT JOIN employee e ON e.id = bl.actor_id
            ORDER BY bl.created_at DESC, bl.id DESC
        """)
    except Exception:
        bike_logs = []

    stock = q("""
        SELECT sps.id, sps.spare_part_catalog_id, sps.darkstore_id,
               sps.quantity, sps.updated_at,
               spc.article, spc.name AS spare_name,
               ds.name AS darkstore_name
        FROM spare_part_stock sps
        LEFT JOIN spare_part_catalog spc ON spc.id = sps.spare_part_catalog_id
        LEFT JOIN darkstore ds ON ds.id = sps.darkstore_id
        ORDER BY ds.name, spc.name
    """)

    spare_catalog = q("""
        SELECT id, article, name, description, COALESCE(price, 0) AS price
        FROM spare_part_catalog ORDER BY name
    """)

    parts_used = q("""
        SELECT rpu.id, rpu.repair_request_id, rpu.spare_part_catalog_id,
               rpu.quantity_used, rpu.created_at,
               spc.article, spc.name AS spare_name,
               rr.type AS repair_type, rr.status AS repair_status,
               rr.bike_id, rr.incoming_id
        FROM repair_parts_used rpu
        LEFT JOIN spare_part_catalog spc ON spc.id = rpu.spare_part_catalog_id
        LEFT JOIN repair_request rr ON rr.id = rpu.repair_request_id
        ORDER BY rpu.created_at DESC, rpu.id DESC
    """)

    work_types = q("SELECT id, name, default_spare_parts FROM work_type ORDER BY name")

    master_stock = q("""
        SELECT mss.id, mss.master_id, mss.spare_part_catalog_id,
               mss.quantity, mss.picked_at, mss.updated_at,
               spc.article, spc.name AS spare_name,
               e.first_name, e.last_name
        FROM master_spare_stock mss
        LEFT JOIN spare_part_catalog spc ON spc.id = mss.spare_part_catalog_id
        LEFT JOIN employee e ON e.id = mss.master_id
        ORDER BY e.last_name, e.first_name, spc.name
    """)

    productivity = q("""
        WITH latest_assignment AS (
            SELECT DISTINCT ON (repair_request_id)
                repair_request_id, assigned_to
            FROM master_assignment
            ORDER BY repair_request_id, assigned_at DESC, id DESC
        ),
        daily AS (
            SELECT la.assigned_to AS employee_id,
                   DATE(rr.updated_at) AS work_day,
                   COUNT(*) AS repairs_done
            FROM repair_request rr
            JOIN latest_assignment la ON la.repair_request_id = rr.id
            WHERE rr.status = 'завершена'
            GROUP BY la.assigned_to, DATE(rr.updated_at)
        )
        SELECT e.id, e.first_name, e.last_name, e.role,
               COALESCE(AVG(d.repairs_done), 0) AS avg_repairs_per_day,
               COALESCE(SUM(d.repairs_done), 0) AS total_repairs,
               COALESCE(COUNT(d.work_day), 0)   AS shift_days
        FROM employee e
        LEFT JOIN daily d ON d.employee_id = e.id
        GROUP BY e.id, e.first_name, e.last_name, e.role
        ORDER BY e.role, e.last_name, e.first_name
    """)

    # Logistics: два связанных запроса через тот же conn
    log_rows = q("""
        SELECT lr.id, lr.request_type, lr.status, lr.notes,
               lr.created_at, lr.updated_at,
               lr.darkstore_id, ds.name AS darkstore_name,
               lr.assigned_to,
               e.first_name AS master_first_name, e.last_name AS master_last_name,
               lr.created_by
        FROM logistics_request lr
        LEFT JOIN darkstore ds ON ds.id = lr.darkstore_id
        LEFT JOIN employee  e  ON e.id  = lr.assigned_to
        ORDER BY lr.created_at DESC
    """)
    try:
        bike_rows = q("SELECT logistics_id, bike_id, direction FROM logistics_bike")
    except Exception:
        bike_rows = [dict(r, direction=None) for r in
                     q("SELECT logistics_id, bike_id FROM logistics_bike")]

    try:
        _conn.close()
    except Exception:
        pass

    # Post-process logistics
    bike_map: dict = {}
    vyvoz_map: dict = {}
    postavka_map: dict = {}
    for br in bike_rows:
        lid = br["logistics_id"]
        bid = br["bike_id"]
        direction = br.get("direction")
        bike_map.setdefault(lid, []).append(bid)
        if direction == "вывоз":
            vyvoz_map.setdefault(lid, []).append(bid)
        elif direction == "поставка":
            postavka_map.setdefault(lid, []).append(bid)

    logistics = []
    for row in log_rows:
        d = dict(row)
        lid = d["id"]
        d["bike_ids"] = bike_map.get(lid, [])
        d["vyvoz_bike_ids"] = vyvoz_map.get(lid, [])
        d["postavka_bike_ids"] = postavka_map.get(lid, [])
        logistics.append(d)

    return {
        "darkstores":       darkstores,
        "employees":        employees,
        "clients":          clients,
        "companies":        companies,
        "rentals":          rentals,
        "bikes":            bikes,
        "incoming_request": incoming_request,
        "repairs":          repairs,
        "bike_logs":        bike_logs,
        "stock":            stock,
        "master_stock":     master_stock,
        "spare_catalog":    spare_catalog,
        "parts_used":       parts_used,
        "work_types":       work_types,
        "productivity":     productivity,
        "logistics":        logistics,
    }

# ===========================================================================
# МУТАЦИИ — ВХОДЯЩИЕ ЗАЯВКИ
# ===========================================================================

def create_incoming_request(
    engine,
    *,
    darkstore: dict,
    device_type: str,
    bike_id: int | None,
    problem: str,
    full_address: str,
) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        if bike_id:
            exists = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM incoming_request
                    WHERE bike_id = :bike_id
                      AND status NOT IN ('завершена','отменена','отменена_куратором','отменена_админом')
                    """
                ),
                {"bike_id": bike_id},
            ).scalar_one()
            if exists:
                raise ValueError("Для этого велосипеда уже есть активная заявка.")

        conn.execute(
            text(
                """
                INSERT INTO incoming_request (
                    request_date, request_type, direction, darkstore_id, bike_id,
                    problem, status, master_id, start_work, end_work, chat_id,
                    full_address, curator_name, device_type, repeat_count,
                    created_at, updated_at
                ) VALUES (
                    :request_date, 'ремонт', :direction, :darkstore_id, :bike_id,
                    :problem, 'новая', NULL, NULL, NULL, :chat_id,
                    :full_address, :curator_name, :device_type, 0,
                    :created_at, :updated_at
                )
                """
            ),
            {
                "request_date": now,
                "direction": darkstore.get("direction"),
                "darkstore_id": darkstore["id"],
                "bike_id": bike_id,
                "problem": problem,
                "chat_id": f"manual-{int(now.timestamp())}",
                "full_address": full_address,
                "curator_name": darkstore.get("name"),
                "device_type": device_type,
                "created_at": now,
                "updated_at": now,
            },
        )

        if bike_id:
            conn.execute(
                text(
                    """
                    UPDATE bike SET tech_status = 'Ожидает выездного ремонта', updated_at = :ts
                    WHERE id = :bike_id
                    """
                ),
                {"ts": now, "bike_id": bike_id},
            )


def assign_incoming_request(
    engine,
    *,
    incoming_id: int,
    assigned_by: int,
    assigned_to: int,
    repair_type: str,
    comment: str,
) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        incoming = conn.execute(
            text("SELECT id, bike_id FROM incoming_request WHERE id = :id"),
            {"id": incoming_id},
        ).mappings().first()
        if not incoming:
            raise ValueError("Входящая заявка не найдена.")

        repair = conn.execute(
            text("SELECT id FROM repair_request WHERE incoming_id = :id ORDER BY id DESC LIMIT 1"),
            {"id": incoming_id},
        ).mappings().first()

        if repair:
            repair_id = repair["id"]
            conn.execute(
                text(
                    "UPDATE repair_request SET type = :type, status = 'назначена', updated_at = :ts WHERE id = :id"
                ),
                {"type": repair_type, "ts": now, "id": repair_id},
            )
        else:
            repair_id = conn.execute(
                text(
                    """
                    INSERT INTO repair_request (
                        bike_id, incoming_id, status, type,
                        postponed_reason, client_rating, client_comment, comment,
                        created_at, updated_at
                    ) VALUES (
                        :bike_id, :incoming_id, 'назначена', :type,
                        NULL, NULL, NULL, NULL, :ts, :ts
                    ) RETURNING id
                    """
                ),
                {"bike_id": incoming.get("bike_id"), "incoming_id": incoming_id, "type": repair_type, "ts": now},
            ).scalar_one()

        conn.execute(
            text(
                """
                INSERT INTO master_assignment (repair_request_id, assigned_by, assigned_to, comment, assigned_at)
                VALUES (:rr_id, :by, :to, :comment, :ts)
                """
            ),
            {
                "rr_id": repair_id,
                "by": assigned_by,
                "to": assigned_to,
                "comment": comment or "Назначение из интерфейса диспетчера",
                "ts": now,
            },
        )

        conn.execute(
            text(
                "UPDATE incoming_request SET status = 'назначена', master_id = :to, updated_at = :ts WHERE id = :id"
            ),
            {"to": assigned_to, "ts": now, "id": incoming_id},
        )

        if incoming.get("bike_id"):
            conn.execute(
                text("UPDATE bike SET tech_status = 'Ожидает выездного ремонта', updated_at = :ts WHERE id = :id"),
                {"ts": now, "id": incoming["bike_id"]},
            )


def update_incoming_request_type(engine, *, incoming_id: int, request_type: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE incoming_request SET request_type = :rt, updated_at = :ts WHERE id = :id"),
            {"rt": request_type, "ts": datetime.now(), "id": incoming_id},
        )


def cancel_incoming_request_by_curator(engine, *, incoming_id: int) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT id, status, bike_id FROM incoming_request WHERE id = :id"),
            {"id": incoming_id},
        ).mappings().first()
        if not row:
            raise ValueError("Заявка не найдена.")
        if row["status"] != "новая":
            raise ValueError("Отменить можно только заявку со статусом «новая».")
        conn.execute(
            text("UPDATE incoming_request SET status = 'отменена_куратором', updated_at = :ts WHERE id = :id"),
            {"ts": now, "id": incoming_id},
        )
        if row["bike_id"]:
            conn.execute(
                text("UPDATE bike SET tech_status = 'Исправен', updated_at = :ts WHERE id = :id"),
                {"ts": now, "id": row["bike_id"]},
            )


def update_incoming_request_problem(engine, *, incoming_id: int, problem: str) -> None:
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT status FROM incoming_request WHERE id = :id"),
            {"id": incoming_id},
        ).mappings().first()
        if not row:
            raise ValueError("Заявка не найдена.")
        if row["status"] != "новая":
            raise ValueError("Редактировать описание можно только у заявки со статусом «новая».")
        conn.execute(
            text("UPDATE incoming_request SET problem = :problem, updated_at = :ts WHERE id = :id"),
            {"problem": problem, "ts": datetime.now(), "id": incoming_id},
        )


def rate_incoming_request(engine, *, incoming_id: int, rating: int) -> None:
    if not 1 <= rating <= 5:
        raise ValueError("Оценка должна быть от 1 до 5.")
    with engine.begin() as conn:
        rr = conn.execute(
            text("SELECT id FROM repair_request WHERE incoming_id = :id ORDER BY id DESC LIMIT 1"),
            {"id": incoming_id},
        ).mappings().first()
        if not rr:
            raise ValueError("По этой заявке нет завершённого ремонта.")
        conn.execute(
            text("UPDATE repair_request SET client_rating = :rating, updated_at = :ts WHERE id = :id"),
            {"rating": rating, "ts": datetime.now(), "id": rr["id"]},
        )


# ===========================================================================
# МУТАЦИИ — РЕМОНТЫ
# ===========================================================================

def start_repair(engine, *, repair_id: int) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        repair = conn.execute(
            text("SELECT id, bike_id, incoming_id FROM repair_request WHERE id = :id"),
            {"id": repair_id},
        ).mappings().first()
        if not repair:
            raise ValueError("Ремонт не найден.")

        conn.execute(
            text("UPDATE repair_request SET status = 'в работе', updated_at = :ts WHERE id = :id"),
            {"ts": now, "id": repair_id},
        )
        if repair.get("incoming_id"):
            conn.execute(
                text(
                    """
                    UPDATE incoming_request
                    SET status = 'в работе', start_work = COALESCE(start_work, :ts), updated_at = :ts
                    WHERE id = :id
                    """
                ),
                {"ts": now, "id": repair["incoming_id"]},
            )
        if repair.get("bike_id"):
            conn.execute(
                text("UPDATE bike SET tech_status = 'В ремонте', updated_at = :ts WHERE id = :id"),
                {"ts": now, "id": repair["bike_id"]},
            )


def postpone_repair(engine, *, repair_id: int, reason: str) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        repair = conn.execute(
            text("SELECT id, bike_id, incoming_id FROM repair_request WHERE id = :id"),
            {"id": repair_id},
        ).mappings().first()
        if not repair:
            raise ValueError("Ремонт не найден.")

        conn.execute(
            text(
                "UPDATE repair_request SET status = 'отложена', postponed_reason = :reason, updated_at = :ts WHERE id = :id"
            ),
            {"reason": reason, "ts": now, "id": repair_id},
        )
        if repair.get("incoming_id"):
            conn.execute(
                text("UPDATE incoming_request SET status = 'отложена', updated_at = :ts WHERE id = :id"),
                {"ts": now, "id": repair["incoming_id"]},
            )
        if repair.get("bike_id"):
            conn.execute(
                text("UPDATE bike SET tech_status = 'Ожидает запчасти', updated_at = :ts WHERE id = :id"),
                {"ts": now, "id": repair["bike_id"]},
            )


def finish_repair(engine, *, repair_id: int, comment: str) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        repair = conn.execute(
            text("SELECT id, bike_id, incoming_id, comment FROM repair_request WHERE id = :id"),
            {"id": repair_id},
        ).mappings().first()
        if not repair:
            raise ValueError("Ремонт не найден.")

        conn.execute(
            text(
                "UPDATE repair_request SET status = 'завершена', comment = :comment, updated_at = :ts WHERE id = :id"
            ),
            {"comment": comment or repair.get("comment"), "ts": now, "id": repair_id},
        )
        if repair.get("incoming_id"):
            conn.execute(
                text(
                    "UPDATE incoming_request SET status = 'завершена', end_work = :ts, updated_at = :ts WHERE id = :id"
                ),
                {"ts": now, "id": repair["incoming_id"]},
            )
        if repair.get("bike_id"):
            conn.execute(
                text("UPDATE bike SET tech_status = 'Исправен', updated_at = :ts WHERE id = :id"),
                {"ts": now, "id": repair["bike_id"]},
            )


def finish_repair_with_vyvoz(engine, *, repair_id: int, comment: str) -> None:
    """Закрыть ремонт и перевести велосипед на склад (физически вывезен с точки)."""
    now = datetime.now()
    with engine.begin() as conn:
        repair = conn.execute(
            text("SELECT id, bike_id, incoming_id, comment FROM repair_request WHERE id = :id"),
            {"id": repair_id},
        ).mappings().first()
        if not repair:
            raise ValueError("Ремонт не найден.")

        conn.execute(
            text(
                "UPDATE repair_request SET status = 'завершена', comment = :comment, updated_at = :ts WHERE id = :id"
            ),
            {"comment": comment or repair.get("comment"), "ts": now, "id": repair_id},
        )
        if repair.get("incoming_id"):
            conn.execute(
                text(
                    "UPDATE incoming_request SET status = 'завершена', end_work = :ts, updated_at = :ts WHERE id = :id"
                ),
                {"ts": now, "id": repair["incoming_id"]},
            )
        if repair.get("bike_id"):
            conn.execute(
                text(
                    """
                    UPDATE bike
                    SET location_status = 'Свободен', tech_status = 'Ожидает ремонта',
                        holder_type = 'stock', holder_id = NULL, darkstore_id = NULL,
                        updated_at = :ts
                    WHERE id = :id
                    """
                ),
                {"ts": now, "id": repair["bike_id"]},
            )


def finish_repair_with_replacement(engine, *, repair_id: int, replacement_bike_id: int, comment: str) -> None:
    """Закрыть ремонт, завершить аренду старого велосипеда и начать новую с заменой."""
    now = datetime.now()
    with engine.begin() as conn:
        repair = conn.execute(
            text("SELECT id, bike_id, incoming_id FROM repair_request WHERE id = :id"),
            {"id": repair_id},
        ).mappings().first()
        if not repair:
            raise ValueError("Ремонт не найден.")
        old_bike_id = repair["bike_id"]
        if not old_bike_id:
            raise ValueError("Ремонт не привязан к велосипеду.")

        replacement = conn.execute(
            text("SELECT id, location_status, tech_status FROM bike WHERE id = :id"),
            {"id": replacement_bike_id},
        ).mappings().first()
        if not replacement:
            raise ValueError("Велосипед для замены не найден.")
        if replacement.get("location_status") != "Свободен":
            raise ValueError("Велосипед для замены уже не свободен.")
        if replacement.get("tech_status") != "Исправен":
            raise ValueError(f"Велосипед для замены не исправен: {replacement.get('tech_status')}.")

        rental = conn.execute(
            text(
                "SELECT id, client_id, start_dt, days_count FROM rental WHERE bike_id = :id AND status = 'активна' LIMIT 1"
            ),
            {"id": old_bike_id},
        ).mappings().first()

        client_darkstore_id = None
        if rental:
            client_row = conn.execute(
                text("SELECT id, darkstore_id FROM client WHERE id = :id"),
                {"id": rental["client_id"]},
            ).mappings().first()
            if client_row:
                client_darkstore_id = client_row.get("darkstore_id")

        conn.execute(
            text(
                "UPDATE repair_request SET status = 'завершена', comment = :comment, updated_at = :ts WHERE id = :id"
            ),
            {"comment": comment or "Замена велосипеда выполнена", "ts": now, "id": repair_id},
        )
        if repair.get("incoming_id"):
            conn.execute(
                text(
                    "UPDATE incoming_request SET status = 'завершена', end_work = :ts, updated_at = :ts WHERE id = :id"
                ),
                {"ts": now, "id": repair["incoming_id"]},
            )

        if rental:
            start_dt = rental.get("start_dt")
            days_count = int(rental.get("days_count") or 0)
            if start_dt:
                days_count = max(days_count, max((now.date() - start_dt.date()).days, 0))
            conn.execute(
                text(
                    "UPDATE rental SET end_dt = :ts, days_count = :days, status = 'завершена', updated_at = :ts WHERE id = :id"
                ),
                {"ts": now, "days": days_count, "id": rental["id"]},
            )

        conn.execute(
            text(
                """
                UPDATE bike
                SET location_status = 'Свободен', tech_status = 'Ожидает ремонта',
                    holder_type = 'stock', holder_id = NULL, darkstore_id = NULL,
                    days_in_rent = 0, updated_at = :ts
                WHERE id = :id
                """
            ),
            {"ts": now, "id": old_bike_id},
        )

        if rental:
            conn.execute(
                text(
                    """
                    INSERT INTO rental (bike_id, client_id, start_dt, end_dt, days_count, status, created_at, updated_at)
                    VALUES (:bike_id, :client_id, :ts, NULL, 0, 'активна', :ts, :ts)
                    """
                ),
                {"bike_id": replacement_bike_id, "client_id": rental["client_id"], "ts": now},
            )
            conn.execute(
                text(
                    """
                    UPDATE bike
                    SET location_status = 'В аренде', holder_type = 'B2B',
                        holder_id = :client_id, darkstore_id = :ds_id,
                        days_in_rent = 0, updated_at = :ts
                    WHERE id = :id
                    """
                ),
                {"client_id": rental["client_id"], "ds_id": client_darkstore_id, "ts": now, "id": replacement_bike_id},
            )
        else:
            conn.execute(
                text("UPDATE bike SET location_status = 'В аренде', updated_at = :ts WHERE id = :id"),
                {"ts": now, "id": replacement_bike_id},
            )


# ===========================================================================
# МУТАЦИИ — ВЕЛОСИПЕДЫ
# ===========================================================================

def validate_bike_identifiers(
    engine,
    *,
    serial_number: str,
    gov_number: str,
    iot_device_id: str,
    exclude_bike_id: int | None = None,
) -> tuple[str, str, str]:
    normalized_serial = (serial_number or "").strip().upper()
    normalized_gov = normalize_gov_number(gov_number)
    normalized_iot = normalize_iot_device_id(iot_device_id)

    if not normalized_serial:
        raise ValueError("Серийный номер обязателен.")
    validate_gov_format(normalized_gov)
    validate_iot_format(normalized_iot)

    with engine.connect() as conn:
        serial_exists = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM bike
                WHERE UPPER(serial_number) = :serial
                  AND (:exclude IS NULL OR id <> :exclude)
                """
            ),
            {"serial": normalized_serial, "exclude": exclude_bike_id},
        ).scalar_one()
        if serial_exists:
            raise ValueError("Велосипед с таким серийным номером уже существует.")

        if normalized_gov:
            gov_exists = conn.execute(
                text(
                    "SELECT COUNT(*) FROM bike WHERE gov_number = :gov AND (:exclude IS NULL OR id <> :exclude)"
                ),
                {"gov": normalized_gov, "exclude": exclude_bike_id},
            ).scalar_one()
            if gov_exists:
                raise ValueError("Велосипед с таким госномером уже существует.")

        if normalized_iot:
            iot_exists = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM bike
                    WHERE UPPER(iot_device_id) = :iot
                      AND (:exclude IS NULL OR id <> :exclude)
                    """
                ),
                {"iot": normalized_iot, "exclude": exclude_bike_id},
            ).scalar_one()
            if iot_exists:
                raise ValueError("Велосипед с таким IoT уже существует.")

    return normalized_serial, normalized_gov, normalized_iot


def update_bike_identity(
    engine,
    *,
    bike_id: int,
    serial_number: str,
    gov_number: str,
    iot_device_id: str,
    tech_status: str,
) -> None:
    s, g, i = validate_bike_identifiers(
        engine, serial_number=serial_number, gov_number=gov_number,
        iot_device_id=iot_device_id, exclude_bike_id=bike_id,
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE bike
                SET serial_number = :serial, gov_number = :gov, iot_device_id = :iot,
                    tech_status = :tech, updated_at = :ts
                WHERE id = :id
                """
            ),
            {"serial": s, "gov": g or None, "iot": i or None, "tech": tech_status, "ts": datetime.now(), "id": bike_id},
        )


def create_new_bike(engine, *, master_id: int, serial_number: str, gov_number: str, model: str, iot_device_id: str) -> int:
    today = date.today()
    now = datetime.now()
    s, g, i = validate_bike_identifiers(
        engine, serial_number=serial_number, gov_number=gov_number, iot_device_id=iot_device_id
    )
    with engine.begin() as conn:
        bike_id = conn.execute(
            text(
                """
                INSERT INTO bike (
                    serial_number, gov_number, model,
                    location_status, tech_status, holder_type, holder_id, darkstore_id,
                    purchase_price, purchase_date, days_in_rent, iot_device_id,
                    created_at, updated_at
                ) VALUES (
                    :serial, :gov, :model,
                    'Свободен', 'Исправен', 'stock', NULL, NULL,
                    0, :purchase_date, 0, :iot,
                    :ts, :ts
                ) RETURNING id
                """
            ),
            {"serial": s, "gov": g or None, "model": model, "purchase_date": today, "iot": i or None, "ts": now},
        ).scalar_one()

        repair_id = conn.execute(
            text(
                """
                INSERT INTO repair_request (
                    bike_id, incoming_id, status, type,
                    postponed_reason, client_rating, client_comment, comment,
                    created_at, updated_at
                ) VALUES (
                    :bike_id, NULL, 'завершена', 'сборка велосипеда',
                    NULL, NULL, NULL, 'Сборка нового велосипеда завершена',
                    :ts, :ts
                ) RETURNING id
                """
            ),
            {"bike_id": bike_id, "ts": now},
        ).scalar_one()

        conn.execute(
            text(
                """
                INSERT INTO master_assignment (repair_request_id, assigned_by, assigned_to, comment, assigned_at)
                VALUES (:rr_id, :master, :master, 'Сборка нового велосипеда', :ts)
                """
            ),
            {"rr_id": repair_id, "master": master_id, "ts": now},
        )

    return int(bike_id)


# ===========================================================================
# МУТАЦИИ — РЕМОНТ ДЕТАЛЕЙ
# ===========================================================================

def create_detail_repair_record(
    engine,
    *,
    master_id: int,
    detail_type: str,
    identifier: str,
    diagnosis: str,
    consumables: list[dict],
) -> int:
    now = datetime.now()
    comment = "\n".join(
        part
        for part in [
            f"Тип детали: {detail_type}",
            f"Идентификатор: {identifier}" if identifier else "",
            diagnosis.strip(),
        ]
        if part
    )
    with engine.begin() as conn:
        repair_id = conn.execute(
            text(
                """
                INSERT INTO repair_request (
                    bike_id, incoming_id, status, type,
                    postponed_reason, client_rating, client_comment, comment,
                    created_at, updated_at
                ) VALUES (
                    NULL, NULL, 'завершена', 'ремонт деталей',
                    NULL, NULL, NULL, :comment,
                    :ts, :ts
                ) RETURNING id
                """
            ),
            {"comment": comment, "ts": now},
        ).scalar_one()

        conn.execute(
            text(
                """
                INSERT INTO master_assignment (repair_request_id, assigned_by, assigned_to, comment, assigned_at)
                VALUES (:rr_id, :master, :master, :comment, :ts)
                """
            ),
            {"rr_id": repair_id, "master": master_id, "comment": f"Ремонт детали: {detail_type}", "ts": now},
        )

    for item in consumables:
        qty = int(item.get("quantity") or 0)
        if qty > 0:
            consume_storage_stock(
                engine,
                spare_part_catalog_id=int(item["spare_part_catalog_id"]),
                repair_request_id=int(repair_id),
                quantity=qty,
            )

    return int(repair_id)


# ===========================================================================
# МУТАЦИИ — АРЕНДА
# ===========================================================================

def issue_b2c_rental(engine, *, bike_id: int, client_id: int, planned_return_dt=None) -> int:
    now = datetime.now()
    with engine.begin() as conn:
        client = conn.execute(text("SELECT id FROM client WHERE id = :id"), {"id": client_id}).mappings().first()
        if not client:
            raise ValueError("Клиент не найден.")

        bike = conn.execute(
            text("SELECT id, serial_number, location_status, tech_status FROM bike WHERE id = :id"),
            {"id": bike_id},
        ).mappings().first()
        if not bike:
            raise ValueError("Велосипед не найден.")
        if bike.get("location_status") != "Свободен":
            raise ValueError(f"Велосипед {bike.get('serial_number') or bike_id} сейчас не свободен.")
        if bike.get("tech_status") != "Исправен":
            raise ValueError(f"Велосипед {bike.get('serial_number') or bike_id} нельзя выдать: техстатус '{bike.get('tech_status')}'.")

        active = conn.execute(
            text("SELECT COUNT(*) FROM rental WHERE bike_id = :id AND status = 'активна'"), {"id": bike_id}
        ).scalar_one()
        if active:
            raise ValueError("По этому велосипеду уже есть активная аренда.")

        conn.execute(
            text(
                """
                INSERT INTO rental (bike_id, client_id, company_id, start_dt, end_dt, days_count, status, created_at, updated_at)
                VALUES (:bike_id, :client_id, NULL, :ts, :end_dt, 0, 'активна', :ts, :ts)
                """
            ),
            {"bike_id": bike_id, "client_id": client_id, "ts": now, "end_dt": planned_return_dt},
        )
        conn.execute(
            text(
                """
                UPDATE bike
                SET location_status = 'В аренде', holder_type = 'B2C',
                    holder_id = :client_id, darkstore_id = NULL, days_in_rent = 0, updated_at = :ts
                WHERE id = :id
                """
            ),
            {"client_id": client_id, "ts": now, "id": bike_id},
        )
    return bike_id


def issue_b2b_rental(engine, *, bike_ids: list[int], company_id: int, darkstore_id: int) -> int:
    now = datetime.now()
    with engine.begin() as conn:
        company = conn.execute(text("SELECT id, name FROM company WHERE id = :id"), {"id": company_id}).mappings().first()
        if not company:
            raise ValueError("Компания не найдена.")
        darkstore = conn.execute(text("SELECT id, company_id, name FROM darkstore WHERE id = :id"), {"id": darkstore_id}).mappings().first()
        if not darkstore:
            raise ValueError("Даркстор не найден.")
        if int(darkstore.get("company_id") or 0) != int(company_id):
            raise ValueError("Этот даркстор не принадлежит выбранной компании.")
        if not bike_ids:
            raise ValueError("Нужно выбрать хотя бы один велосипед.")

        inserted = 0
        for bid in bike_ids:
            bike = conn.execute(
                text("SELECT id, serial_number, location_status, tech_status FROM bike WHERE id = :id"), {"id": bid}
            ).mappings().first()
            if not bike:
                raise ValueError(f"Велосипед #{bid} не найден.")
            if bike.get("location_status") != "Свободен":
                raise ValueError(f"Велосипед {bike.get('serial_number') or bid} сейчас не свободен.")
            if bike.get("tech_status") != "Исправен":
                raise ValueError(f"Велосипед {bike.get('serial_number') or bid} нельзя выдать: техстатус '{bike.get('tech_status')}'.")
            active = conn.execute(
                text("SELECT COUNT(*) FROM rental WHERE bike_id = :id AND status = 'активна'"), {"id": bid}
            ).scalar_one()
            if active:
                raise ValueError(f"По велосипеду {bike.get('serial_number') or bid} уже есть активная аренда.")

            conn.execute(
                text(
                    """
                    INSERT INTO rental (bike_id, client_id, company_id, start_dt, end_dt, days_count, status, created_at, updated_at)
                    VALUES (:bid, NULL, :cid, :ts, NULL, 0, 'активна', :ts, :ts)
                    """
                ),
                {"bid": bid, "cid": company_id, "ts": now},
            )
            conn.execute(
                text(
                    """
                    UPDATE bike
                    SET location_status = 'В аренде', holder_type = 'B2B',
                        holder_id = :cid, darkstore_id = :ds_id, days_in_rent = 0, updated_at = :ts
                    WHERE id = :id
                    """
                ),
                {"cid": company_id, "ds_id": darkstore_id, "ts": now, "id": bid},
            )
            inserted += 1
    return inserted


def finish_rental(engine, *, rental_id: int) -> int:
    now = datetime.now()
    with engine.begin() as conn:
        rental = conn.execute(
            text("SELECT id, bike_id, start_dt, days_count, status, end_dt FROM rental WHERE id = :id"),
            {"id": rental_id},
        ).mappings().first()
        if not rental:
            raise ValueError("Аренда не найдена.")
        if rental.get("end_dt") is not None or rental.get("status") != "активна":
            raise ValueError("Эта аренда уже завершена.")

        start_dt = rental.get("start_dt")
        days_count = int(rental.get("days_count") or 0)
        if start_dt:
            elapsed = max((now.date() - start_dt.date()).days, 0)
            days_count = max(days_count, elapsed)

        conn.execute(
            text(
                "UPDATE rental SET end_dt = :ts, days_count = :days, status = 'завершена', updated_at = :ts WHERE id = :id"
            ),
            {"ts": now, "days": days_count, "id": rental_id},
        )
        conn.execute(
            text(
                """
                UPDATE bike
                SET location_status = 'Свободен', tech_status = 'Ожидает ремонта',
                    holder_type = 'stock', holder_id = NULL, darkstore_id = NULL,
                    days_in_rent = 0, updated_at = :ts
                WHERE id = :id
                """
            ),
            {"ts": now, "id": rental["bike_id"]},
        )
    return int(rental["bike_id"])


def report_rental_theft(engine, *, rental_id: int) -> int:
    now = datetime.now()
    with engine.begin() as conn:
        rental = conn.execute(
            text("SELECT id, bike_id, status FROM rental WHERE id = :id"), {"id": rental_id}
        ).mappings().first()
        if not rental:
            raise ValueError("Аренда не найдена.")
        if rental.get("status") != "активна":
            raise ValueError("Сообщить о краже можно только по активной аренде.")

        conn.execute(
            text("UPDATE rental SET end_dt = :ts, status = 'отменена', updated_at = :ts WHERE id = :id"),
            {"ts": now, "id": rental_id},
        )
        conn.execute(
            text(
                """
                UPDATE bike
                SET location_status = 'Кража', holder_type = 'stock',
                    holder_id = NULL, darkstore_id = NULL, days_in_rent = 0, updated_at = :ts
                WHERE id = :id
                """
            ),
            {"ts": now, "id": rental["bike_id"]},
        )
    return int(rental["bike_id"])


# ===========================================================================
# МУТАЦИИ — КЛИЕНТЫ И КОМПАНИИ
# ===========================================================================

def create_private_client(engine, *, name: str, phone: str, passport_data: dict | None = None) -> int:
    now = datetime.now()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                SELECT setval(
                    'client_id_seq',
                    GREATEST(
                        COALESCE((SELECT MAX(id) FROM client), 0),
                        COALESCE((SELECT last_value FROM client_id_seq), 0)
                    )
                )
                """
            )
        )
        return int(
            conn.execute(
                text(
                    """
                    INSERT INTO client (type, name, phone, passport_data, darkstore_id, created_at, updated_at)
                    VALUES ('физлицо', :name, :phone, CAST(:passport_data AS jsonb), NULL, :ts, :ts)
                    RETURNING id
                    """
                ),
                {
                    "name": name.strip(),
                    "phone": phone.strip(),
                    "passport_data": json.dumps(passport_data or {}, ensure_ascii=False),
                    "ts": now,
                },
            ).scalar_one()
        )


def create_company(engine, *, name: str, company_type: str) -> int:
    now = datetime.now()
    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    "INSERT INTO company (name, type, created_at) VALUES (:name, :type, :ts) RETURNING id"
                ),
                {"name": name.strip(), "type": company_type.strip() or "B2B", "ts": now},
            ).scalar_one()
        )


# ===========================================================================
# МУТАЦИИ — РЕМОНТ В ЦЕХУ
# ===========================================================================

def ensure_workshop_repair(engine, *, bike_id: int, master_id: int) -> int:
    now = datetime.now()
    with engine.begin() as conn:
        existing = conn.execute(
            text(
                """
                WITH latest_assignment AS (
                    SELECT DISTINCT ON (repair_request_id)
                        repair_request_id, assigned_to
                    FROM master_assignment
                    ORDER BY repair_request_id, assigned_at DESC, id DESC
                )
                SELECT rr.id
                FROM repair_request rr
                LEFT JOIN latest_assignment la ON la.repair_request_id = rr.id
                WHERE rr.bike_id = :bike_id
                  AND rr.type = 'внутренний ремонт'
                  AND rr.status IN ('назначена','в работе','отложена')
                  AND (la.assigned_to = :master_id OR la.assigned_to IS NULL)
                ORDER BY rr.updated_at DESC, rr.id DESC
                LIMIT 1
                """
            ),
            {"bike_id": bike_id, "master_id": master_id},
        ).mappings().first()

        if existing:
            repair_id = int(existing["id"])
            conn.execute(
                text("UPDATE repair_request SET status = 'в работе', updated_at = :ts WHERE id = :id"),
                {"ts": now, "id": repair_id},
            )
        else:
            repair_id = conn.execute(
                text(
                    """
                    INSERT INTO repair_request (
                        bike_id, incoming_id, status, type,
                        postponed_reason, client_rating, client_comment, comment,
                        created_at, updated_at
                    ) VALUES (
                        :bike_id, NULL, 'в работе', 'внутренний ремонт',
                        NULL, NULL, NULL, NULL, :ts, :ts
                    ) RETURNING id
                    """
                ),
                {"bike_id": bike_id, "ts": now},
            ).scalar_one()

            conn.execute(
                text(
                    """
                    INSERT INTO master_assignment (repair_request_id, assigned_by, assigned_to, comment, assigned_at)
                    VALUES (:rr_id, :master, :master, 'Мастер цеха взял велосипед в работу', :ts)
                    """
                ),
                {"rr_id": repair_id, "master": master_id, "ts": now},
            )

        conn.execute(
            text("UPDATE bike SET tech_status = 'В ремонте', updated_at = :ts WHERE id = :id"),
            {"ts": now, "id": bike_id},
        )
    return int(repair_id)


# ===========================================================================
# МУТАЦИИ — ЗАПЧАСТИ
# ===========================================================================

def consume_storage_stock(engine, *, spare_part_catalog_id: int, repair_request_id: int, quantity: int) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        if quantity <= 0:
            raise ValueError("Количество должно быть больше нуля.")

        stock_rows = conn.execute(
            text(
                """
                SELECT id, quantity FROM spare_part_stock
                WHERE spare_part_catalog_id = :cid AND quantity > 0
                ORDER BY quantity DESC, id ASC
                """
            ),
            {"cid": spare_part_catalog_id},
        ).mappings().all()

        total = sum(int(row.get("quantity") or 0) for row in stock_rows)
        if total < quantity:
            raise ValueError("На складе недостаточно этой запчасти.")

        remaining = quantity
        for row in stock_rows:
            if remaining <= 0:
                break
            take = min(int(row.get("quantity") or 0), remaining)
            conn.execute(
                text("UPDATE spare_part_stock SET quantity = quantity - :q, updated_at = :ts WHERE id = :id"),
                {"q": take, "ts": now, "id": row["id"]},
            )
            remaining -= take

        existing = conn.execute(
            text(
                "SELECT id FROM repair_parts_used WHERE repair_request_id = :rr AND spare_part_catalog_id = :cid"
            ),
            {"rr": repair_request_id, "cid": spare_part_catalog_id},
        ).mappings().first()

        if existing:
            conn.execute(
                text("UPDATE repair_parts_used SET quantity_used = quantity_used + :q WHERE id = :id"),
                {"q": quantity, "id": existing["id"]},
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO repair_parts_used (repair_request_id, spare_part_catalog_id, quantity_used, created_at)
                    VALUES (:rr, :cid, :q, :ts)
                    """
                ),
                {"rr": repair_request_id, "cid": spare_part_catalog_id, "q": quantity, "ts": now},
            )


def adjust_stock(engine, *, stock_id: int | None, spare_part_catalog_id: int, darkstore_id: int, delta: int) -> None:
    with engine.begin() as conn:
        if stock_id:
            if delta < 0:
                current = conn.execute(
                    text("SELECT quantity FROM spare_part_stock WHERE id = :id"), {"id": stock_id}
                ).scalar_one()
                if int(current or 0) < -delta:
                    raise ValueError("На складе недостаточно запчастей для списания.")
            conn.execute(
                text("UPDATE spare_part_stock SET quantity = quantity + :delta, updated_at = :ts WHERE id = :id"),
                {"delta": delta, "ts": datetime.now(), "id": stock_id},
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO spare_part_stock (spare_part_catalog_id, darkstore_id, quantity, updated_at)
                    VALUES (:cid, :ds_id, :q, :ts)
                    """
                ),
                {"cid": spare_part_catalog_id, "ds_id": darkstore_id, "q": max(delta, 0), "ts": datetime.now()},
            )


def transfer_catalog_stock_to_master(engine, *, spare_part_catalog_id: int, master_id: int, quantity: int) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        if quantity <= 0:
            raise ValueError("Количество должно быть больше нуля.")

        stock_rows = conn.execute(
            text(
                """
                SELECT id, quantity FROM spare_part_stock
                WHERE spare_part_catalog_id = :cid AND quantity > 0
                ORDER BY quantity DESC, id ASC
                """
            ),
            {"cid": spare_part_catalog_id},
        ).mappings().all()

        total = sum(int(row.get("quantity") or 0) for row in stock_rows)
        if total < quantity:
            raise ValueError("На складе недостаточно запчастей для перевода мастеру.")

        remaining = quantity
        for row in stock_rows:
            if remaining <= 0:
                break
            move = min(int(row.get("quantity") or 0), remaining)
            conn.execute(
                text("UPDATE spare_part_stock SET quantity = quantity - :q, updated_at = :ts WHERE id = :id"),
                {"q": move, "ts": now, "id": row["id"]},
            )
            remaining -= move

        master_row = conn.execute(
            text(
                "SELECT id FROM master_spare_stock WHERE master_id = :mid AND spare_part_catalog_id = :cid"
            ),
            {"mid": master_id, "cid": spare_part_catalog_id},
        ).mappings().first()

        if master_row:
            conn.execute(
                text("UPDATE master_spare_stock SET quantity = quantity + :q, updated_at = :ts WHERE id = :id"),
                {"q": quantity, "ts": now, "id": master_row["id"]},
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO master_spare_stock (master_id, spare_part_catalog_id, quantity, picked_at, updated_at)
                    VALUES (:mid, :cid, :q, :ts, :ts)
                    """
                ),
                {"mid": master_id, "cid": spare_part_catalog_id, "q": quantity, "ts": now},
            )


def consume_master_stock_by_catalog(
    engine, *, spare_part_catalog_id: int, master_id: int, repair_request_id: int, quantity: int
) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, quantity FROM master_spare_stock WHERE master_id = :mid AND spare_part_catalog_id = :cid AND quantity > 0 ORDER BY id ASC"
            ),
            {"mid": master_id, "cid": spare_part_catalog_id},
        ).mappings().all()
        total = sum(int(r["quantity"]) for r in rows)
        if quantity <= 0:
            raise ValueError("Количество должно быть больше нуля.")
        if total < quantity:
            raise ValueError("В багажнике недостаточно запчастей.")

        remaining = quantity
        for row in rows:
            if remaining <= 0:
                break
            take = min(int(row["quantity"]), remaining)
            conn.execute(
                text("UPDATE master_spare_stock SET quantity = quantity - :q, updated_at = :ts WHERE id = :id"),
                {"q": take, "ts": now, "id": row["id"]},
            )
            remaining -= take

        existing = conn.execute(
            text(
                "SELECT id FROM repair_parts_used WHERE repair_request_id = :rr AND spare_part_catalog_id = :cid"
            ),
            {"rr": repair_request_id, "cid": spare_part_catalog_id},
        ).mappings().first()

        if existing:
            conn.execute(
                text("UPDATE repair_parts_used SET quantity_used = quantity_used + :q WHERE id = :id"),
                {"q": quantity, "id": existing["id"]},
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO repair_parts_used (repair_request_id, spare_part_catalog_id, quantity_used, created_at)
                    VALUES (:rr, :cid, :q, :ts)
                    """
                ),
                {"rr": repair_request_id, "cid": spare_part_catalog_id, "q": quantity, "ts": now},
            )


def return_master_stock_by_catalog_id(engine, *, spare_part_catalog_id: int, master_id: int, quantity: int) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, quantity FROM master_spare_stock WHERE master_id = :mid AND spare_part_catalog_id = :cid AND quantity > 0 ORDER BY id ASC"
            ),
            {"mid": master_id, "cid": spare_part_catalog_id},
        ).mappings().all()
        total = sum(int(r["quantity"]) for r in rows)
        if quantity <= 0:
            raise ValueError("Количество должно быть больше нуля.")
        if total < quantity:
            raise ValueError("В багажнике недостаточно запчастей для возврата.")

        remaining = quantity
        for row in rows:
            if remaining <= 0:
                break
            take = min(int(row["quantity"]), remaining)
            conn.execute(
                text("UPDATE master_spare_stock SET quantity = quantity - :q, updated_at = :ts WHERE id = :id"),
                {"q": take, "ts": now, "id": row["id"]},
            )
            remaining -= take

        stock_row = conn.execute(
            text(
                "SELECT id FROM spare_part_stock WHERE spare_part_catalog_id = :cid ORDER BY quantity DESC, id ASC LIMIT 1"
            ),
            {"cid": spare_part_catalog_id},
        ).mappings().first()
        if not stock_row:
            raise ValueError("Складская позиция для возврата не найдена. Обратитесь к кладовщику.")
        conn.execute(
            text("UPDATE spare_part_stock SET quantity = quantity + :q, updated_at = :ts WHERE id = :id"),
            {"q": quantity, "ts": now, "id": stock_row["id"]},
        )


# ===========================================================================
# ИМПОРТ ИЗ M4
# ===========================================================================

# Статусы M4, которые считаем «закрытыми» — не импортируем
_M4_CLOSED_STATUSES = {
    "закрыта", "закрыто", "выполнена", "выполнено", "отменена", "отменено",
    "closed", "done", "cancelled", "canceled",
}

# Маппинг колонок M4 → наши имена (регистронезависимо, без пробелов по краям)
_M4_COL_MAP = {
    "номер":            "external_id",
    "дата создания":    "created_at",
    "заголовок":        "problem",
    "контрагент":       "darkstore_name",
    "объект":           "gov_number_raw",
    "тип задачи":       "device_type",
    "приоритет":        "priority",
    "выполнить до":     "deadline",
    "статус":           "m4_status",
}


def import_m4_xlsx(engine, file_bytes: bytes) -> tuple[int, int]:
    """
    Читает xlsx-выгрузку из M4, импортирует новые заявки в incoming_request.

    Возвращает (imported_count, skipped_count).
    skipped = дубли по external_id + закрытые статусы.
    """
    import io
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("Для импорта M4 нужна библиотека openpyxl. Установите: pip install openpyxl")

    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Файл пустой.")

    # Определяем индексы нужных колонок
    header = [str(cell or "").strip().lower() for cell in rows[0]]
    col_idx: dict[str, int] = {}
    for m4_name, our_name in _M4_COL_MAP.items():
        try:
            col_idx[our_name] = header.index(m4_name)
        except ValueError:
            pass  # колонки может не быть — не критично

    if "external_id" not in col_idx:
        raise ValueError(
            "В файле нет колонки «Номер». Проверьте, что загружаете правильную выгрузку из M4."
        )

    # Загружаем существующие external_id чтобы не дублировать
    with engine.connect() as conn:
        existing_ids = {
            str(row[0])
            for row in conn.execute(
                text("SELECT external_id FROM incoming_request WHERE external_id IS NOT NULL")
            ).fetchall()
        }
        # Матч gov_number → bike_id
        bikes_raw = conn.execute(
            text("SELECT id, gov_number FROM bike WHERE gov_number IS NOT NULL")
        ).mappings().all()
    gov_to_bike_id = {
        (str(b["gov_number"]).strip().upper()): int(b["id"])
        for b in bikes_raw
        if b["gov_number"]
    }

    now = datetime.now()
    imported = 0
    skipped = 0

    with engine.begin() as conn:
        for data_row in rows[1:]:
            if all(v is None for v in data_row):
                continue  # пустая строка

            def _get(field: str):
                idx = col_idx.get(field)
                if idx is None:
                    return None
                val = data_row[idx]
                return str(val).strip() if val is not None else None

            external_id = _get("external_id")
            if not external_id:
                skipped += 1
                continue

            # Пропускаем дубли
            if external_id in existing_ids:
                skipped += 1
                continue

            # Пропускаем закрытые
            m4_status = (_get("m4_status") or "").lower()
            if m4_status in _M4_CLOSED_STATUSES:
                skipped += 1
                continue

            # Парсим даты
            def _parse_dt(val):
                if val is None:
                    return None
                if isinstance(val, datetime):
                    return val
                try:
                    return datetime.fromisoformat(str(val))
                except (ValueError, TypeError):
                    return None

            created_at_raw = col_idx.get("created_at")
            created_at = _parse_dt(data_row[created_at_raw]) if created_at_raw is not None else now

            deadline_raw = col_idx.get("deadline")
            deadline = _parse_dt(data_row[deadline_raw]) if deadline_raw is not None else None

            # Матч велосипеда по гос номеру
            gov_raw = (_get("gov_number_raw") or "").upper().replace(" ", "")
            bike_id = gov_to_bike_id.get(gov_raw)

            problem = _get("problem") or "Заявка из M4"
            darkstore_name = _get("darkstore_name")
            device_type = _get("device_type") or "Велосипед"
            priority = _get("priority")

            conn.execute(
                text(
                    """
                    INSERT INTO incoming_request
                        (source, external_id, problem, darkstore_name, bike_id,
                         gov_number, device_type, priority, deadline,
                         status, created_at, updated_at)
                    VALUES
                        ('m4', :external_id, :problem, :darkstore_name, :bike_id,
                         :gov_number, :device_type, :priority, :deadline,
                         'новая', :created_at, :updated_at)
                    """
                ),
                {
                    "external_id":    external_id,
                    "problem":        problem,
                    "darkstore_name": darkstore_name,
                    "bike_id":        bike_id,
                    "gov_number":     gov_raw or None,
                    "device_type":    device_type,
                    "priority":       priority,
                    "deadline":       deadline,
                    "created_at":     created_at or now,
                    "updated_at":     now,
                },
            )
            existing_ids.add(external_id)
            imported += 1

    return imported, skipped


# ===========================================================================
# ЛОГИСТИКА — ВЫВОЗЫ И ПОСТАВКИ
# ===========================================================================

def create_logistics_request(
    engine,
    *,
    request_type: str,
    darkstore_id: int,
    bike_ids: list[int] | None = None,
    notes: str = "",
    created_by: int,
    vyvoz_bike_ids: list[int] | None = None,
    postavka_bike_ids: list[int] | None = None,
) -> int:
    """Создаёт заявку на логистику и привязывает байки. Возвращает id.

    Для типа 'замена' передавать vyvoz_bike_ids (старые байки с даркстора)
    и postavka_bike_ids (новые байки со склада). bike_ids используется для
    вывоза и поставки.
    """
    if request_type == "замена":
        if not vyvoz_bike_ids:
            raise ValueError("Для замены укажите байки на вывоз.")
        if not postavka_bike_ids:
            raise ValueError("Для замены укажите байки на поставку.")
        all_bike_ids = list(vyvoz_bike_ids) + list(postavka_bike_ids)
    else:
        effective_ids = bike_ids or []
        if not effective_ids:
            raise ValueError("Укажите хотя бы один велосипед.")
        all_bike_ids = effective_ids

    now = datetime.now()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO logistics_request
                    (request_type, darkstore_id, status, created_by, notes, created_at, updated_at)
                VALUES
                    (:rtype, :ds_id, 'новая', :created_by, :notes, :ts, :ts)
                RETURNING id
                """
            ),
            {"rtype": request_type, "ds_id": darkstore_id, "created_by": created_by,
             "notes": notes or None, "ts": now},
        ).mappings().first()
        logistics_id = row["id"]

        if request_type == "замена":
            for bike_id in (vyvoz_bike_ids or []):
                conn.execute(
                    text("INSERT INTO logistics_bike (logistics_id, bike_id, direction) VALUES (:lid, :bid, 'вывоз')"),
                    {"lid": logistics_id, "bid": bike_id},
                )
            for bike_id in (postavka_bike_ids or []):
                conn.execute(
                    text("INSERT INTO logistics_bike (logistics_id, bike_id, direction) VALUES (:lid, :bid, 'поставка')"),
                    {"lid": logistics_id, "bid": bike_id},
                )
        else:
            for bike_id in (bike_ids or []):
                conn.execute(
                    text("INSERT INTO logistics_bike (logistics_id, bike_id) VALUES (:lid, :bid)"),
                    {"lid": logistics_id, "bid": bike_id},
                )
    return logistics_id


def assign_logistics_request(engine, *, logistics_id: int, assigned_to: int) -> None:
    """Назначает выездного мастера на логистическую заявку."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE logistics_request
                SET assigned_to = :emp, status = 'назначена', updated_at = :ts
                WHERE id = :lid
                """
            ),
            {"emp": assigned_to, "ts": datetime.now(), "lid": logistics_id},
        )


def complete_logistics_request(engine, *, logistics_id: int) -> None:
    """
    Завершает логистическую заявку и обновляет статусы байков:
    - вывоз  → location_status='Свободен', holder_type='stock', darkstore_id=NULL
    - поставка → location_status='В аренде', holder_type='B2B', darkstore_id=<darkstore>
    """
    now = datetime.now()
    with engine.begin() as conn:
        lr = conn.execute(
            text("SELECT id, request_type, darkstore_id FROM logistics_request WHERE id = :lid"),
            {"lid": logistics_id},
        ).mappings().first()
        if not lr:
            raise ValueError("Заявка не найдена.")

        bike_rows = conn.execute(
            text("SELECT bike_id, direction FROM logistics_bike WHERE logistics_id = :lid"),
            {"lid": logistics_id},
        ).mappings().all()

        if lr["request_type"] == "замена":
            vyvoz_ids = [r["bike_id"] for r in bike_rows if r["direction"] == "вывоз"]
            postavka_ids = [r["bike_id"] for r in bike_rows if r["direction"] == "поставка"]
            for bid in vyvoz_ids:
                conn.execute(
                    text(
                        """
                        UPDATE bike
                        SET location_status = 'Свободен', tech_status = 'Ожидает ремонта',
                            holder_type = 'stock', holder_id = NULL, darkstore_id = NULL,
                            updated_at = :ts
                        WHERE id = :bid
                        """
                    ),
                    {"ts": now, "bid": bid},
                )
            for bid in postavka_ids:
                conn.execute(
                    text(
                        """
                        UPDATE bike
                        SET location_status = 'В аренде', holder_type = 'B2B',
                            darkstore_id = :ds_id, updated_at = :ts
                        WHERE id = :bid
                        """
                    ),
                    {"ds_id": lr["darkstore_id"], "ts": now, "bid": bid},
                )
            conn.execute(
                text("UPDATE logistics_request SET status = 'выполнена', updated_at = :ts WHERE id = :lid"),
                {"ts": now, "lid": logistics_id},
            )
            return

        bike_ids = [r["bike_id"] for r in bike_rows]

        if lr["request_type"] == "вывоз":
            for bid in bike_ids:
                conn.execute(
                    text(
                        """
                        UPDATE bike
                        SET location_status = 'Свободен', tech_status = 'Ожидает ремонта',
                            holder_type = 'stock', holder_id = NULL, darkstore_id = NULL,
                            updated_at = :ts
                        WHERE id = :bid
                        """
                    ),
                    {"ts": now, "bid": bid},
                )
        else:  # поставка
            ds_id = lr["darkstore_id"]
            for bid in bike_ids:
                conn.execute(
                    text(
                        """
                        UPDATE bike
                        SET location_status = 'В аренде', holder_type = 'B2B',
                            darkstore_id = :ds_id, updated_at = :ts
                        WHERE id = :bid
                        """
                    ),
                    {"ds_id": ds_id, "ts": now, "bid": bid},
                )

        conn.execute(
            text("UPDATE logistics_request SET status = 'выполнена', updated_at = :ts WHERE id = :lid"),
            {"ts": now, "lid": logistics_id},
        )


# ===========================================================================
# ЦЕХОВОЙ КОНТРОЛЬ КАЧЕСТВА — СТАРШИЙ МАСТЕР ЦЕХА
# ===========================================================================

def submit_for_review(engine, *, repair_id: int) -> None:
    """Мастер цеха отправляет ремонт на проверку старшему мастеру."""
    now = datetime.now()
    with engine.begin() as conn:
        repair = conn.execute(
            text("SELECT id, status FROM repair_request WHERE id = :id"),
            {"id": repair_id},
        ).mappings().first()
        if not repair:
            raise ValueError("Ремонт не найден.")
        if repair["status"] not in ("в работе", "назначена", "ожидает запчасти"):
            raise ValueError(f"Нельзя отправить на проверку ремонт со статусом «{repair['status']}».")
        conn.execute(
            text("UPDATE repair_request SET status = 'на проверке', updated_at = :ts WHERE id = :id"),
            {"ts": now, "id": repair_id},
        )


def approve_repair(engine, *, repair_id: int, comment: str = "") -> None:
    """Старший мастер принимает ремонт: велосипед → Исправен, ремонт → завершена."""
    now = datetime.now()
    with engine.begin() as conn:
        repair = conn.execute(
            text("SELECT id, bike_id, incoming_id, comment, status FROM repair_request WHERE id = :id"),
            {"id": repair_id},
        ).mappings().first()
        if not repair:
            raise ValueError("Ремонт не найден.")
        if repair["status"] != "на проверке":
            raise ValueError("Принять можно только ремонт со статусом «на проверке».")

        final_comment = comment.strip() or repair.get("comment") or ""
        conn.execute(
            text(
                "UPDATE repair_request SET status = 'завершена', comment = :comment, updated_at = :ts WHERE id = :id"
            ),
            {"comment": final_comment, "ts": now, "id": repair_id},
        )
        if repair.get("bike_id"):
            conn.execute(
                text("UPDATE bike SET tech_status = 'Исправен', updated_at = :ts WHERE id = :id"),
                {"ts": now, "id": repair["bike_id"]},
            )
        if repair.get("incoming_id"):
            conn.execute(
                text(
                    "UPDATE incoming_request SET status = 'завершена', end_work = :ts, updated_at = :ts WHERE id = :id"
                ),
                {"ts": now, "id": repair["incoming_id"]},
            )


def reject_repair(engine, *, repair_id: int, comment: str) -> None:
    """Старший мастер отправляет ремонт на доработку — считается косяком."""
    now = datetime.now()
    if not comment.strip():
        raise ValueError("Укажите причину отправки на доработку.")
    with engine.begin() as conn:
        repair = conn.execute(
            text("SELECT id, bike_id, status FROM repair_request WHERE id = :id"),
            {"id": repair_id},
        ).mappings().first()
        if not repair:
            raise ValueError("Ремонт не найден.")
        if repair["status"] != "на проверке":
            raise ValueError("На доработку можно отправить только ремонт со статусом «на проверке».")
        conn.execute(
            text(
                """
                UPDATE repair_request
                SET status = 'в работе',
                    rework_count = rework_count + 1,
                    comment = :comment,
                    updated_at = :ts
                WHERE id = :id
                """
            ),
            {"comment": comment.strip(), "ts": now, "id": repair_id},
        )


@st.cache_data(ttl=60)
def load_reviews_pending(_engine):
    """Ремонты на проверке у старшего мастера."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                WITH last_assign AS (
                    SELECT DISTINCT ON (repair_request_id)
                        repair_request_id, assigned_to
                    FROM master_assignment
                    ORDER BY repair_request_id, assigned_at DESC, id DESC
                )
                SELECT
                    rr.id, rr.bike_id, rr.status, rr.type, rr.comment,
                    rr.rework_count, rr.updated_at, rr.created_at,
                    b.serial_number, b.gov_number, b.model, b.tech_status,
                    e.id AS master_id,
                    e.first_name AS master_first_name,
                    e.last_name  AS master_last_name
                FROM repair_request rr
                LEFT JOIN bike b ON b.id = rr.bike_id
                LEFT JOIN last_assign la ON la.repair_request_id = rr.id
                LEFT JOIN employee e ON e.id = la.assigned_to
                WHERE rr.status = 'на проверке'
                ORDER BY rr.updated_at ASC
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]




@st.cache_data(ttl=60)
def load_rework_stats(_engine):
    """Статистика переделок по мастерам для старшего мастера."""
    with _engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                e.id,
                e.first_name,
                e.last_name,
                COUNT(rr.id)                                      AS total,
                SUM(CASE WHEN rr.rework_count > 0 THEN 1 ELSE 0 END) AS reworks,
                ROUND(
                    100.0 * SUM(CASE WHEN rr.rework_count > 0 THEN 1 ELSE 0 END)
                    / NULLIF(COUNT(rr.id), 0), 1
                )                                                 AS rework_pct
            FROM employee e
            LEFT JOIN master_assignment ma ON ma.assigned_to = e.id
            LEFT JOIN repair_request rr ON rr.id = ma.repair_request_id
              AND rr.status IN ('завершена', 'на проверке')
            WHERE e.role = 'мастер_цеха'
            GROUP BY e.id, e.first_name, e.last_name
            ORDER BY rework_pct DESC NULLS LAST
        """)).mappings().all()
    return [dict(row) for row in rows]


# ===========================================================================
# ЛОГИСТИКА — ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ
# ===========================================================================

def update_bike_gov_number(engine, *, bike_id: int, gov_number: str) -> None:
    """Обновляет гос номер байка."""
    gov_number = (gov_number or "").strip()
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE bike SET gov_number = :gn, updated_at = :ts WHERE id = :bid"),
            {"gn": gov_number or None, "ts": datetime.now(), "bid": bike_id},
        )


def cancel_logistics_request(engine, *, logistics_id: int) -> None:
    """
    Отменяет логистическую заявку: удаляет связи с байками и саму заявку.
    Можно отменять только если статус != 'выполнена'.
    """
    with engine.begin() as conn:
        lr = conn.execute(
            text("SELECT id, status FROM logistics_request WHERE id = :lid"),
            {"lid": logistics_id},
        ).mappings().first()
        if not lr:
            raise ValueError("Заявка не найдена.")
        if lr["status"] == "выполнена":
            raise ValueError("Нельзя отменить выполненную заявку.")
        conn.execute(
            text("DELETE FROM logistics_bike WHERE logistics_id = :lid"),
            {"lid": logistics_id},
        )
        conn.execute(
            text("DELETE FROM logistics_request WHERE id = :lid"),
            {"lid": logistics_id},
        )
