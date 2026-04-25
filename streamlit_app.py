import html
import json
import re
from datetime import date, datetime

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError


st.set_page_config(page_title="Vanta ERP", page_icon="V", layout="wide")


ROLE_LABELS = {
    "curator": "Куратор / Даркстор",
    "dispatcher": "Диспетчер",
    "field_master": "Выездной мастер",
    "workshop_master": "Мастер цеха",
    "warehouse": "Склад",
}

EMPLOYEE_ROLE_MAP = {
    "dispatcher": ("диспетчер",),
    "field_master": ("выездной_мастер",),
    "workshop_master": ("мастер_цеха",),
    "warehouse": ("кладовщик",),
}

ACTIVE_REQUEST_STATUSES = {"новая", "назначена", "в работе", "отложена", "ожидает запчасти", "замена_вело", "замена вело"}
ACTIVE_MASTER_STATUSES = {"назначена", "в работе", "отложена", "ожидает запчасти", "замена вело"}
DONE_REQUEST_STATUSES = {"завершена", "отменена", "отменена_куратором", "отменена_админом"}


def format_dt(value) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime("%d.%m.%Y %H:%M")


def format_short_date(value) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime("%d.%m.%Y")


def full_name(row: dict) -> str:
    first_name = (row.get("first_name") or "").strip()
    last_name = (row.get("last_name") or "").strip()
    name = f"{last_name} {first_name}".strip()
    return name or "—"


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg: #f4f4f5;
            --panel: #ffffff;
            --ink: #0f0f10;
            --muted: #6d6d74;
            --line: rgba(15, 15, 16, 0.08);
            --line-strong: rgba(15, 15, 16, 0.14);
            --accent: #d0021b;
            --accent-soft: rgba(208, 2, 27, 0.08);
            --shadow: 0 16px 36px rgba(15, 15, 16, 0.06);
        }

        .stApp {
            background: var(--bg);
            color: var(--ink);
        }

        .block-container {
            padding-top: 1.25rem;
            padding-bottom: 2rem;
        }

        section[data-testid="stSidebar"] {
            background: #23242d;
        }

        section[data-testid="stSidebar"] * {
            color: #ffffff;
        }

        section[data-testid="stSidebar"] .stSelectbox label,
        section[data-testid="stSidebar"] .stRadio label {
            color: #ffffff !important;
        }

        .hero {
            background: #101012;
            color: #ffffff;
            border-radius: 30px;
            padding: 30px 36px;
            box-shadow: 0 20px 54px rgba(15, 15, 16, 0.18);
            margin-bottom: 1rem;
        }

        .hero-eyebrow {
            font-size: 0.76rem;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            opacity: 0.68;
        }

        .hero-title {
            font-size: 2.3rem;
            font-weight: 850;
            margin: 0.35rem 0 0.55rem 0;
        }

        .hero-subtitle {
            font-size: 1rem;
            line-height: 1.55;
            color: rgba(255, 255, 255, 0.84);
            max-width: 920px;
        }

        .hero-context {
            margin-top: 0.9rem;
            font-size: 1.08rem;
            font-weight: 800;
            color: #ffffff;
        }

        .hero-note {
            margin-top: 0.24rem;
            color: rgba(255, 255, 255, 0.78);
            font-size: 0.95rem;
        }

        .metric-card {
            background: var(--panel);
            border: 1px solid var(--line);
            border-top: 4px solid var(--accent);
            border-radius: 24px;
            padding: 18px 20px;
            min-height: 120px;
            box-shadow: var(--shadow);
            margin-bottom: 0.3rem;
        }

        .metric-label {
            color: var(--muted);
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }

        .metric-value {
            color: var(--ink);
            font-size: 2.05rem;
            font-weight: 850;
            line-height: 1;
            margin: 0.42rem 0 0.24rem 0;
        }

        .metric-note {
            color: var(--muted);
            font-size: 0.93rem;
            line-height: 1.4;
        }

        .record-card {
            background: #ffffff;
            border: 1px solid rgba(15, 15, 16, 0.08);
            border-radius: 26px;
            padding: 20px 22px 18px 22px;
            box-shadow: 0 14px 34px rgba(15, 15, 16, 0.045);
            margin: 0 0 18px 0;
        }

        .record-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 16px;
            margin-bottom: 14px;
        }

        .record-title {
            font-size: 1.15rem;
            font-weight: 850;
            color: var(--ink);
            margin-bottom: 0.22rem;
        }

        .record-subtitle {
            font-size: 0.93rem;
            color: var(--muted);
            line-height: 1.45;
        }

        .record-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 14px 18px;
        }

        .record-field {
            border-top: 1px solid var(--line);
            padding-top: 10px;
        }

        .record-field-label {
            color: var(--muted);
            font-size: 0.76rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            margin-bottom: 0.3rem;
        }

        .record-field-value {
            color: var(--ink);
            font-size: 1rem;
            font-weight: 650;
            line-height: 1.38;
        }

        .chip {
            display: inline-flex;
            align-items: center;
            padding: 0.38rem 0.8rem;
            border-radius: 999px;
            font-size: 0.82rem;
            font-weight: 800;
            white-space: nowrap;
            border: 1px solid transparent;
        }

        .chip-dark {
            background: #111111;
            color: #ffffff;
        }

        .chip-red {
            background: #d0021b;
            color: #ffffff;
        }

        .chip-soft-red {
            background: rgba(208, 2, 27, 0.1);
            color: #980011;
            border-color: rgba(208, 2, 27, 0.14);
        }

        .chip-default {
            background: #efeff1;
            color: #222228;
        }

        .pill-row {
            margin-bottom: 0.85rem;
        }

        .pill {
            display: inline-block;
            padding: 0.36rem 0.72rem;
            border-radius: 999px;
            margin-right: 0.42rem;
            margin-bottom: 0.4rem;
            background: #ececef;
            color: #17171a;
            font-size: 0.82rem;
            font-weight: 750;
        }

        .pill.red {
            background: rgba(208, 2, 27, 0.1);
            color: #980011;
        }

        .empty {
            border: 1px dashed var(--line-strong);
            border-radius: 18px;
            background: #fafafa;
            padding: 18px;
            color: var(--muted);
        }

        .subtle-note {
            color: var(--muted);
            font-size: 0.92rem;
        }

        .section-title {
            font-size: 1.95rem;
            font-weight: 850;
            margin: 0.45rem 0 0.75rem 0;
        }

        .section-caption {
            color: var(--muted);
            margin: -0.25rem 0 0.85rem 0;
        }

        div[role="radiogroup"] {
            gap: 10px;
        }

        div[role="radiogroup"] label {
            background: #ffffff;
            border: 1px solid rgba(15, 15, 16, 0.12);
            border-radius: 16px;
            min-height: 48px;
            padding: 10px 16px;
            box-shadow: 0 4px 10px rgba(15, 15, 16, 0.02);
        }

        div[role="radiogroup"] label:has(input:checked) {
            background: #111111;
            border-color: #111111;
        }

        div[role="radiogroup"] label:has(input:checked) p {
            color: #ffffff !important;
        }

        div[role="radiogroup"] p {
            font-weight: 800;
            color: #111111;
        }

        div[data-testid="stWidgetLabel"] p,
        label[data-testid="stWidgetLabel"] p {
            color: #111111 !important;
            font-weight: 700 !important;
        }

        .stTextInput input,
        .stTextArea textarea {
            background: #1a1b20 !important;
            color: #ffffff !important;
            border: 1px solid #1a1b20 !important;
        }

        .stTextInput input::placeholder,
        .stTextArea textarea::placeholder {
            color: rgba(255,255,255,0.66) !important;
        }

        .stSelectbox [data-baseweb="select"] > div,
        .stMultiSelect [data-baseweb="select"] > div {
            background: #ffffff !important;
            color: #111111 !important;
            border-color: rgba(15, 15, 16, 0.14) !important;
        }

        .stButton button,
        .stFormSubmitButton button,
        .stDownloadButton button,
        button[data-testid^="stBaseButton-"] {
            border-radius: 14px !important;
            border: 1px solid rgba(15, 15, 16, 0.14) !important;
            background: #ffffff !important;
            color: #111111 !important;
            font-weight: 750 !important;
            box-shadow: none !important;
        }

        .stButton button *,
        .stFormSubmitButton button *,
        .stDownloadButton button *,
        button[kind="primary"] *,
        button[data-testid="stBaseButton-primary"] *,
        button[data-testid^="stBaseButton-"] * {
            color: inherit !important;
            fill: currentColor !important;
            stroke: currentColor !important;
        }

        .stButton button[kind="primary"],
        .stButton button[data-testid="stBaseButton-primary"],
        .stFormSubmitButton button[kind="primary"],
        .stFormSubmitButton button[data-testid="stBaseButton-primary"] {
            background: #111111 !important;
            color: #ffffff !important;
            border-color: #111111 !important;
        }

        .stButton button[kind="primary"]:hover,
        .stButton button[data-testid="stBaseButton-primary"]:hover,
        .stFormSubmitButton button[kind="primary"]:hover,
        .stFormSubmitButton button[data-testid="stBaseButton-primary"]:hover {
            background: #1b1c22 !important;
            color: #ffffff !important;
            border-color: #1b1c22 !important;
        }

        .stButton button:hover,
        .stFormSubmitButton button:hover,
        .stDownloadButton button:hover,
        button[data-testid^="stBaseButton-"]:hover {
            background: #f2f2f4 !important;
            color: #111111 !important;
            border-color: rgba(15, 15, 16, 0.22) !important;
        }

        .stButton button[kind="primary"]:hover *,
        .stButton button[data-testid="stBaseButton-primary"]:hover *,
        .stFormSubmitButton button[kind="primary"]:hover *,
        .stFormSubmitButton button[data-testid="stBaseButton-primary"]:hover * {
            color: #ffffff !important;
            fill: #ffffff !important;
            stroke: #ffffff !important;
        }

        .stButton button[kind="primary"],
        .stButton button[data-testid="stBaseButton-primary"],
        .stFormSubmitButton button[kind="primary"],
        .stFormSubmitButton button[data-testid="stBaseButton-primary"] {
            background: #111111 !important;
            color: #ffffff !important;
        }

        .stButton button[kind="primary"] p,
        .stButton button[data-testid="stBaseButton-primary"] p,
        .stFormSubmitButton button[kind="primary"] p,
        .stFormSubmitButton button[data-testid="stBaseButton-primary"] p,
        .stButton button[kind="primary"] span,
        .stButton button[data-testid="stBaseButton-primary"] span,
        .stFormSubmitButton button[kind="primary"] span,
        .stFormSubmitButton button[data-testid="stBaseButton-primary"] span {
            color: #ffffff !important;
        }

        .stButton button p,
        .stFormSubmitButton button p,
        .stDownloadButton button p,
        .stButton button span,
        .stFormSubmitButton button span,
        .stDownloadButton button span {
            color: inherit !important;
        }

        @media (max-width: 960px) {
            .record-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }

        @media (max-width: 640px) {
            .record-grid {
                grid-template-columns: 1fr;
            }
            .record-top {
                flex-direction: column;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def normalize_supabase_database_url(raw_url: str, project_ref: str | None) -> str:
    url = make_url(raw_url)
    host = url.host or ""
    username = url.username or ""
    if host.endswith("pooler.supabase.com"):
        if "." not in username:
            if not project_ref:
                raise ValueError("Для Supabase pooler нужен SUPABASE_PROJECT_REF или логин вида postgres.<project_ref>.")
            url = url.set(username=f"{username}.{project_ref}")
        if url.port == 6543:
            url = url.set(port=5432)
    return url.render_as_string(hide_password=False)


@st.cache_resource
def get_engine():
    raw_url = st.secrets["DATABASE_URL"]
    project_ref = st.secrets.get("SUPABASE_PROJECT_REF")
    db_url = normalize_supabase_database_url(raw_url, project_ref)
    return create_engine(
        db_url,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=0,
        connect_args={"connect_timeout": 10, "sslmode": "require"},
    )


def verify_connection_twice(engine) -> None:
    for _ in range(2):
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))


def check_database_connection(engine, attempts: int = 2) -> tuple[bool, str | None]:
    last_error = None
    for _ in range(attempts):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True, None
        except SQLAlchemyError as exc:
            last_error = str(exc)
    return False, last_error


def refresh_all_caches() -> None:
    st.cache_data.clear()


def flash_success(message: str) -> None:
    st.session_state["flash_success"] = message


def render_flash() -> None:
    message = st.session_state.pop("flash_success", None)
    if message:
        st.success(message)


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
                    SELECT COUNT(*)
                    FROM incoming_request
                    WHERE bike_id = :bike_id
                      AND status NOT IN ('завершена', 'отменена', 'отменена_куратором', 'отменена_админом')
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
                    request_date,
                    request_type,
                    direction,
                    darkstore_id,
                    bike_id,
                    problem,
                    status,
                    master_id,
                    start_work,
                    end_work,
                    chat_id,
                    full_address,
                    curator_name,
                    device_type,
                    repeat_count,
                    created_at,
                    updated_at
                ) VALUES (
                    :request_date,
                    'ремонт',
                    :direction,
                    :darkstore_id,
                    :bike_id,
                    :problem,
                    'новая',
                    NULL,
                    NULL,
                    NULL,
                    :chat_id,
                    :full_address,
                    :curator_name,
                    :device_type,
                    0,
                    :created_at,
                    :updated_at
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
                    UPDATE bike
                    SET tech_status = 'Ожидает выездного ремонта',
                        updated_at = :updated_at
                    WHERE id = :bike_id
                    """
                ),
                {"updated_at": now, "bike_id": bike_id},
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
            text("SELECT id, bike_id FROM incoming_request WHERE id = :incoming_id"),
            {"incoming_id": incoming_id},
        ).mappings().first()
        if not incoming:
            raise ValueError("Входящая заявка не найдена.")

        repair = conn.execute(
            text("SELECT id FROM repair_request WHERE incoming_id = :incoming_id ORDER BY id DESC LIMIT 1"),
            {"incoming_id": incoming_id},
        ).mappings().first()

        if repair:
            repair_id = repair["id"]
            conn.execute(
                text(
                    """
                    UPDATE repair_request
                    SET type = :repair_type,
                        status = 'назначена',
                        updated_at = :updated_at
                    WHERE id = :repair_id
                    """
                ),
                {"repair_type": repair_type, "updated_at": now, "repair_id": repair_id},
            )
        else:
            repair_id = conn.execute(
                text(
                    """
                    INSERT INTO repair_request (
                        bike_id,
                        incoming_id,
                        status,
                        type,
                        postponed_reason,
                        client_rating,
                        client_comment,
                        comment,
                        created_at,
                        updated_at
                    ) VALUES (
                        :bike_id,
                        :incoming_id,
                        'назначена',
                        :repair_type,
                        NULL,
                        NULL,
                        NULL,
                        NULL,
                        :created_at,
                        :updated_at
                    )
                    RETURNING id
                    """
                ),
                {
                    "bike_id": incoming.get("bike_id"),
                    "incoming_id": incoming_id,
                    "repair_type": repair_type,
                    "created_at": now,
                    "updated_at": now,
                },
            ).scalar_one()

        conn.execute(
            text(
                """
                INSERT INTO master_assignment (
                    repair_request_id,
                    assigned_by,
                    assigned_to,
                    comment,
                    assigned_at
                ) VALUES (
                    :repair_request_id,
                    :assigned_by,
                    :assigned_to,
                    :comment,
                    :assigned_at
                )
                """
            ),
            {
                "repair_request_id": repair_id,
                "assigned_by": assigned_by,
                "assigned_to": assigned_to,
                "comment": comment or "Назначение из интерфейса диспетчера",
                "assigned_at": now,
            },
        )

        conn.execute(
            text(
                """
                UPDATE incoming_request
                SET status = 'назначена',
                    master_id = :master_id,
                    updated_at = :updated_at
                WHERE id = :incoming_id
                """
            ),
            {"master_id": assigned_to, "updated_at": now, "incoming_id": incoming_id},
        )

        if incoming.get("bike_id"):
            conn.execute(
                text(
                    """
                    UPDATE bike
                    SET tech_status = 'Ожидает выездного ремонта',
                        updated_at = :updated_at
                    WHERE id = :bike_id
                    """
                ),
                {"updated_at": now, "bike_id": incoming["bike_id"]},
            )


def update_incoming_request_type(engine, *, incoming_id: int, request_type: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE incoming_request
                SET request_type = :request_type,
                    updated_at = :updated_at
                WHERE id = :incoming_id
                """
            ),
            {"request_type": request_type, "updated_at": datetime.now(), "incoming_id": incoming_id},
        )


def start_repair(engine, *, repair_id: int) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        repair = conn.execute(
            text("SELECT id, bike_id, incoming_id FROM repair_request WHERE id = :repair_id"),
            {"repair_id": repair_id},
        ).mappings().first()
        if not repair:
            raise ValueError("Ремонт не найден.")

        conn.execute(
            text(
                """
                UPDATE repair_request
                SET status = 'в работе',
                    updated_at = :updated_at
                WHERE id = :repair_id
                """
            ),
            {"updated_at": now, "repair_id": repair_id},
        )

        if repair.get("incoming_id"):
            conn.execute(
                text(
                    """
                    UPDATE incoming_request
                    SET status = 'в работе',
                        start_work = COALESCE(start_work, :start_work),
                        updated_at = :updated_at
                    WHERE id = :incoming_id
                    """
                ),
                {"start_work": now, "updated_at": now, "incoming_id": repair["incoming_id"]},
            )

        if repair.get("bike_id"):
            conn.execute(
                text(
                    """
                    UPDATE bike
                    SET tech_status = 'В ремонте',
                        updated_at = :updated_at
                    WHERE id = :bike_id
                    """
                ),
                {"updated_at": now, "bike_id": repair["bike_id"]},
            )


def postpone_repair(engine, *, repair_id: int, reason: str) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        repair = conn.execute(
            text("SELECT id, bike_id, incoming_id FROM repair_request WHERE id = :repair_id"),
            {"repair_id": repair_id},
        ).mappings().first()
        if not repair:
            raise ValueError("Ремонт не найден.")

        conn.execute(
            text(
                """
                UPDATE repair_request
                SET status = 'отложена',
                    postponed_reason = :reason,
                    updated_at = :updated_at
                WHERE id = :repair_id
                """
            ),
            {"reason": reason, "updated_at": now, "repair_id": repair_id},
        )

        if repair.get("incoming_id"):
            conn.execute(
                text(
                    """
                    UPDATE incoming_request
                    SET status = 'отложена',
                        updated_at = :updated_at
                    WHERE id = :incoming_id
                    """
                ),
                {"updated_at": now, "incoming_id": repair["incoming_id"]},
            )

        if repair.get("bike_id"):
            conn.execute(
                text(
                    """
                    UPDATE bike
                    SET tech_status = 'Ожидает запчасти',
                        updated_at = :updated_at
                    WHERE id = :bike_id
                    """
                ),
                {"updated_at": now, "bike_id": repair["bike_id"]},
            )


def finish_repair(engine, *, repair_id: int, comment: str) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        repair = conn.execute(
            text("SELECT id, bike_id, incoming_id, comment FROM repair_request WHERE id = :repair_id"),
            {"repair_id": repair_id},
        ).mappings().first()
        if not repair:
            raise ValueError("Ремонт не найден.")

        conn.execute(
            text(
                """
                UPDATE repair_request
                SET status = 'завершена',
                    comment = :comment,
                    updated_at = :updated_at
                WHERE id = :repair_id
                """
            ),
            {"comment": comment or repair.get("comment"), "updated_at": now, "repair_id": repair_id},
        )

        if repair.get("incoming_id"):
            conn.execute(
                text(
                    """
                    UPDATE incoming_request
                    SET status = 'завершена',
                        end_work = :end_work,
                        updated_at = :updated_at
                    WHERE id = :incoming_id
                    """
                ),
                {"end_work": now, "updated_at": now, "incoming_id": repair["incoming_id"]},
            )

        if repair.get("bike_id"):
            conn.execute(
                text(
                    """
                    UPDATE bike
                    SET tech_status = 'Исправен',
                        updated_at = :updated_at
                    WHERE id = :bike_id
                    """
                ),
                {"updated_at": now, "bike_id": repair["bike_id"]},
            )


LATIN_TO_CYRILLIC_GOV_MAP = str.maketrans(
    {
        "A": "А",
        "B": "В",
        "C": "С",
        "E": "Е",
        "H": "Н",
        "K": "К",
        "M": "М",
        "O": "О",
        "P": "Р",
        "T": "Т",
        "X": "Х",
        "Y": "У",
    }
)


def normalize_gov_number(value: str) -> str:
    cleaned = (value or "").strip().upper().replace(" ", "")
    cleaned = cleaned.translate(LATIN_TO_CYRILLIC_GOV_MAP)
    return cleaned


def normalize_iot_device_id(value: str) -> str:
    return (value or "").strip().upper().replace(" ", "")


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

    if normalized_gov and not re.fullmatch(r"[А-ЯЁ0-9]+", normalized_gov):
        raise ValueError("В госномере должны быть только заглавные русские буквы и цифры.")

    if normalized_iot and not re.fullmatch(r"25-\d{4}", normalized_iot):
        raise ValueError("IoT должен быть в формате 25-1234.")

    with engine.connect() as conn:
        params = {"serial_number": normalized_serial, "exclude_bike_id": exclude_bike_id}
        serial_exists = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM bike
                WHERE UPPER(serial_number) = :serial_number
                  AND (:exclude_bike_id IS NULL OR id <> :exclude_bike_id)
                """
            ),
            params,
        ).scalar_one()
        if serial_exists:
            raise ValueError("Велосипед с таким серийным номером уже существует.")

        if normalized_gov:
            gov_exists = conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM bike
                    WHERE gov_number = :gov_number
                      AND (:exclude_bike_id IS NULL OR id <> :exclude_bike_id)
                    """
                ),
                {"gov_number": normalized_gov, "exclude_bike_id": exclude_bike_id},
            ).scalar_one()
            if gov_exists:
                raise ValueError("Велосипед с таким госномером уже существует.")

        if normalized_iot:
            iot_exists = conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM bike
                    WHERE UPPER(iot_device_id) = :iot_device_id
                      AND (:exclude_bike_id IS NULL OR id <> :exclude_bike_id)
                    """
                ),
                {"iot_device_id": normalized_iot, "exclude_bike_id": exclude_bike_id},
            ).scalar_one()
            if iot_exists:
                raise ValueError("Велосипед с таким IoT уже существует.")

    return normalized_serial, normalized_gov, normalized_iot


def update_bike_identity(
    engine,
    *,
    serial_number: str,
    bike_id: int,
    gov_number: str,
    iot_device_id: str,
    tech_status: str,
) -> None:
    normalized_serial, normalized_gov, normalized_iot = validate_bike_identifiers(
        engine,
        serial_number=serial_number,
        gov_number=gov_number,
        iot_device_id=iot_device_id,
        exclude_bike_id=bike_id,
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE bike
                SET serial_number = :serial_number,
                    gov_number = :gov_number,
                    iot_device_id = :iot_device_id,
                    tech_status = :tech_status,
                    updated_at = :updated_at
                WHERE id = :bike_id
                """
            ),
            {
                "serial_number": normalized_serial,
                "gov_number": normalized_gov or None,
                "iot_device_id": normalized_iot or None,
                "tech_status": tech_status,
                "updated_at": datetime.now(),
                "bike_id": bike_id,
            },
        )


def create_new_bike(
    engine,
    *,
    master_id: int,
    serial_number: str,
    gov_number: str,
    model: str,
    iot_device_id: str,
) -> None:
    today = date.today()
    now = datetime.now()
    normalized_serial, normalized_gov, normalized_iot = validate_bike_identifiers(
        engine,
        serial_number=serial_number,
        gov_number=gov_number,
        iot_device_id=iot_device_id,
    )
    with engine.begin() as conn:
        bike_id = conn.execute(
            text(
                """
                INSERT INTO bike (
                    serial_number,
                    gov_number,
                    model,
                    location_status,
                    tech_status,
                    holder_type,
                    holder_id,
                    darkstore_id,
                    purchase_price,
                    purchase_date,
                    days_in_rent,
                    iot_device_id,
                    created_at,
                    updated_at
                ) VALUES (
                    :serial_number,
                    :gov_number,
                    :model,
                    'Свободен',
                    'Исправен',
                    'stock',
                    NULL,
                    NULL,
                    0,
                    :purchase_date,
                    0,
                    :iot_device_id,
                    :created_at,
                    :updated_at
                )
                RETURNING id
                """
            ),
            {
                "serial_number": normalized_serial,
                "gov_number": normalized_gov or None,
                "model": model,
                "purchase_date": today,
                "iot_device_id": normalized_iot or None,
                "created_at": now,
                "updated_at": now,
            },
        ).scalar_one()

        repair_id = conn.execute(
            text(
                """
                INSERT INTO repair_request (
                    bike_id,
                    incoming_id,
                    status,
                    type,
                    postponed_reason,
                    client_rating,
                    client_comment,
                    comment,
                    created_at,
                    updated_at
                ) VALUES (
                    :bike_id,
                    NULL,
                    'завершена',
                    'сборка велосипеда',
                    NULL,
                    NULL,
                    NULL,
                    :comment,
                    :created_at,
                    :updated_at
                )
                RETURNING id
                """
            ),
            {
                "bike_id": bike_id,
                "comment": "Сборка нового велосипеда завершена",
                "created_at": now,
                "updated_at": now,
            },
        ).scalar_one()

        conn.execute(
            text(
                """
                INSERT INTO master_assignment (
                    repair_request_id,
                    assigned_by,
                    assigned_to,
                    comment,
                    assigned_at
                ) VALUES (
                    :repair_request_id,
                    :assigned_by,
                    :assigned_to,
                    :comment,
                    :assigned_at
                )
                """
            ),
            {
                "repair_request_id": repair_id,
                "assigned_by": master_id,
                "assigned_to": master_id,
                "comment": "Сборка нового велосипеда",
                "assigned_at": now,
            },
        )

    return int(bike_id)


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
    with engine.begin() as conn:
        repair_id = conn.execute(
            text(
                """
                INSERT INTO repair_request (
                    bike_id,
                    incoming_id,
                    status,
                    type,
                    postponed_reason,
                    client_rating,
                    client_comment,
                    comment,
                    created_at,
                    updated_at
                ) VALUES (
                    NULL,
                    NULL,
                    'завершена',
                    'ремонт деталей',
                    NULL,
                    NULL,
                    NULL,
                    :comment,
                    :created_at,
                    :updated_at
                )
                RETURNING id
                """
            ),
            {
                "comment": "\n".join(
                    part
                    for part in [
                        f"Тип детали: {detail_type}",
                        f"Идентификатор: {identifier}" if identifier else "",
                        diagnosis.strip(),
                    ]
                    if part
                ),
                "created_at": now,
                "updated_at": now,
            },
        ).scalar_one()

        conn.execute(
            text(
                """
                INSERT INTO master_assignment (
                    repair_request_id,
                    assigned_by,
                    assigned_to,
                    comment,
                    assigned_at
                ) VALUES (
                    :repair_request_id,
                    :assigned_by,
                    :assigned_to,
                    :comment,
                    :assigned_at
                )
                """
            ),
            {
                "repair_request_id": repair_id,
                "assigned_by": master_id,
                "assigned_to": master_id,
                "comment": f"Ремонт детали: {detail_type}",
                "assigned_at": now,
            },
        )

    for item in consumables:
        qty = int(item.get("quantity") or 0)
        if qty <= 0:
            continue
        consume_storage_stock(
            engine,
            spare_part_catalog_id=int(item["spare_part_catalog_id"]),
            repair_request_id=int(repair_id),
            quantity=qty,
        )

    return int(repair_id)


def issue_rental_batch(
    engine,
    *,
    bike_ids: list[int],
    client_id: int,
    darkstore_id: int | None,
) -> int:
    now = datetime.now()
    with engine.begin() as conn:
        client = conn.execute(
            text(
                """
                SELECT id, type, name
                FROM client
                WHERE id = :client_id
                """
            ),
            {"client_id": client_id},
        ).mappings().first()
        if not client:
            raise ValueError("Клиент не найден.")

        if not bike_ids:
            raise ValueError("Нужно выбрать хотя бы один велосипед.")

        holder_type = "B2C" if (client.get("type") or "").strip().lower() == "физлицо" else "B2B"
        inserted = 0

        for bike_id in bike_ids:
            bike = conn.execute(
                text(
                    """
                    SELECT id, serial_number, location_status, tech_status
                    FROM bike
                    WHERE id = :bike_id
                    """
                ),
                {"bike_id": bike_id},
            ).mappings().first()
            if not bike:
                raise ValueError(f"Велосипед #{bike_id} не найден.")
            if bike.get("location_status") != "Свободен":
                raise ValueError(f"Велосипед {bike.get('serial_number') or bike_id} сейчас не свободен.")
            if bike.get("tech_status") != "Исправен":
                raise ValueError(f"Велосипед {bike.get('serial_number') or bike_id} нельзя выдать: техстатус '{bike.get('tech_status')}'.")

            active_rental = conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM rental
                    WHERE bike_id = :bike_id
                      AND status = 'активна'
                      AND end_dt IS NULL
                    """
                ),
                {"bike_id": bike_id},
            ).scalar_one()
            if active_rental:
                raise ValueError(f"По велосипеду {bike.get('serial_number') or bike_id} уже есть активная аренда.")

            conn.execute(
                text(
                    """
                    INSERT INTO rental (
                        bike_id,
                        client_id,
                        start_dt,
                        end_dt,
                        days_count,
                        status,
                        created_at,
                        updated_at
                    ) VALUES (
                        :bike_id,
                        :client_id,
                        :start_dt,
                        NULL,
                        0,
                        'активна',
                        :created_at,
                        :updated_at
                    )
                    """
                ),
                {
                    "bike_id": bike_id,
                    "client_id": client_id,
                    "start_dt": now,
                    "created_at": now,
                    "updated_at": now,
                },
            )

            conn.execute(
                text(
                    """
                    UPDATE bike
                    SET location_status = 'В аренде',
                        holder_type = :holder_type,
                        holder_id = :holder_id,
                        darkstore_id = :darkstore_id,
                        days_in_rent = 0,
                        updated_at = :updated_at
                    WHERE id = :bike_id
                    """
                ),
                {
                    "holder_type": holder_type,
                    "holder_id": client_id,
                    "darkstore_id": darkstore_id,
                    "updated_at": now,
                    "bike_id": bike_id,
                },
            )
            inserted += 1

    return inserted


def finish_rental(engine, *, rental_id: int) -> int:
    now = datetime.now()
    with engine.begin() as conn:
        rental = conn.execute(
            text(
                """
                SELECT id, bike_id, start_dt, days_count, status, end_dt
                FROM rental
                WHERE id = :rental_id
                """
            ),
            {"rental_id": rental_id},
        ).mappings().first()
        if not rental:
            raise ValueError("Аренда не найдена.")
        if rental.get("end_dt") is not None or rental.get("status") != "активна":
            raise ValueError("Эта аренда уже завершена.")

        start_dt = rental.get("start_dt")
        days_count = int(rental.get("days_count") or 0)
        if start_dt:
            elapsed_days = max((now.date() - start_dt.date()).days, 0)
            days_count = max(days_count, elapsed_days)

        conn.execute(
            text(
                """
                UPDATE rental
                SET end_dt = :end_dt,
                    days_count = :days_count,
                    status = 'завершена',
                    updated_at = :updated_at
                WHERE id = :rental_id
                """
            ),
            {
                "end_dt": now,
                "days_count": days_count,
                "updated_at": now,
                "rental_id": rental_id,
            },
        )

        conn.execute(
            text(
                """
                UPDATE bike
                SET location_status = 'Свободен',
                    tech_status = 'Ожидает ремонта',
                    holder_type = 'stock',
                    holder_id = NULL,
                    darkstore_id = NULL,
                    days_in_rent = 0,
                    updated_at = :updated_at
                WHERE id = :bike_id
                """
            ),
            {
                "updated_at": now,
                "bike_id": rental["bike_id"],
            },
        )

    return int(rental["bike_id"])


def issue_rental_flow(
    engine,
    *,
    bike_ids: list[int],
    client_id: int,
    planned_return_dt=None,
) -> int:
    now = datetime.now()
    with engine.begin() as conn:
        client = conn.execute(
            text(
                """
                SELECT id, type, name, darkstore_id
                FROM client
                WHERE id = :client_id
                """
            ),
            {"client_id": client_id},
        ).mappings().first()
        if not client:
            raise ValueError("Клиент не найден.")
        if not bike_ids:
            raise ValueError("Нужно выбрать хотя бы один велосипед.")

        is_b2c = (client.get("type") or "").strip().lower() == "физлицо"
        holder_type = "B2C" if is_b2c else "B2B"
        resolved_darkstore_id = None if is_b2c else client.get("darkstore_id")
        if not is_b2c and resolved_darkstore_id is None:
            raise ValueError("У B2B-клиента не привязан даркстор.")

        inserted = 0
        for bike_id in bike_ids:
            bike = conn.execute(
                text(
                    """
                    SELECT id, serial_number, location_status, tech_status
                    FROM bike
                    WHERE id = :bike_id
                    """
                ),
                {"bike_id": bike_id},
            ).mappings().first()
            if not bike:
                raise ValueError(f"Велосипед #{bike_id} не найден.")
            if bike.get("location_status") != "Свободен":
                raise ValueError(f"Велосипед {bike.get('serial_number') or bike_id} сейчас не свободен.")
            if bike.get("tech_status") != "Исправен":
                raise ValueError(
                    f"Велосипед {bike.get('serial_number') or bike_id} нельзя выдать: техстатус '{bike.get('tech_status')}'."
                )

            active_rental = conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM rental
                    WHERE bike_id = :bike_id
                      AND status = 'активна'
                    """
                ),
                {"bike_id": bike_id},
            ).scalar_one()
            if active_rental:
                raise ValueError(f"По велосипеду {bike.get('serial_number') or bike_id} уже есть активная аренда.")

            conn.execute(
                text(
                    """
                    INSERT INTO rental (
                        bike_id,
                        client_id,
                        start_dt,
                        end_dt,
                        days_count,
                        status,
                        created_at,
                        updated_at
                    ) VALUES (
                        :bike_id,
                        :client_id,
                        :start_dt,
                        :end_dt,
                        0,
                        'активна',
                        :created_at,
                        :updated_at
                    )
                    """
                ),
                {
                    "bike_id": bike_id,
                    "client_id": client_id,
                    "start_dt": now,
                    "end_dt": planned_return_dt,
                    "created_at": now,
                    "updated_at": now,
                },
            )

            conn.execute(
                text(
                    """
                    UPDATE bike
                    SET location_status = 'В аренде',
                        holder_type = :holder_type,
                        holder_id = :holder_id,
                        darkstore_id = :darkstore_id,
                        days_in_rent = 0,
                        updated_at = :updated_at
                    WHERE id = :bike_id
                    """
                ),
                {
                    "holder_type": holder_type,
                    "holder_id": client_id,
                    "darkstore_id": resolved_darkstore_id,
                    "updated_at": now,
                    "bike_id": bike_id,
                },
            )
            inserted += 1

    return inserted


def report_rental_theft(engine, *, rental_id: int) -> int:
    now = datetime.now()
    with engine.begin() as conn:
        rental = conn.execute(
            text(
                """
                SELECT id, bike_id, status
                FROM rental
                WHERE id = :rental_id
                """
            ),
            {"rental_id": rental_id},
        ).mappings().first()
        if not rental:
            raise ValueError("Аренда не найдена.")
        if rental.get("status") != "активна":
            raise ValueError("Сообщить о краже можно только по активной аренде.")

        conn.execute(
            text(
                """
                UPDATE rental
                SET end_dt = :end_dt,
                    status = 'отменена',
                    updated_at = :updated_at
                WHERE id = :rental_id
                """
            ),
            {"end_dt": now, "updated_at": now, "rental_id": rental_id},
        )

        conn.execute(
            text(
                """
                UPDATE bike
                SET location_status = 'Кража',
                    holder_type = 'stock',
                    holder_id = NULL,
                    darkstore_id = NULL,
                    days_in_rent = 0,
                    updated_at = :updated_at
                WHERE id = :bike_id
                """
            ),
            {"updated_at": now, "bike_id": rental["bike_id"]},
        )

    return int(rental["bike_id"])


def ensure_rental_company_schema(engine) -> None:
    with engine.begin() as conn:
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


def create_client(engine, *, name: str, phone: str) -> int:
    now = datetime.now()
    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    """
                    INSERT INTO client (type, name, phone, darkstore_id, created_at, updated_at)
                    VALUES ('физлицо', :name, :phone, NULL, :created_at, :updated_at)
                    RETURNING id
                    """
                ),
                {"name": name.strip(), "phone": phone.strip(), "created_at": now, "updated_at": now},
            ).scalar_one()
        )


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
                    VALUES ('физлицо', :name, :phone, CAST(:passport_data AS jsonb), NULL, :created_at, :updated_at)
                    RETURNING id
                    """
                ),
                {
                    "name": name.strip(),
                    "phone": phone.strip(),
                    "passport_data": json.dumps(passport_data or {}, ensure_ascii=False),
                    "created_at": now,
                    "updated_at": now,
                },
            ).scalar_one()
        )


def create_company(engine, *, name: str, company_type: str) -> int:
    now = datetime.now()
    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    """
                    INSERT INTO company (name, type, created_at)
                    VALUES (:name, :type, :created_at)
                    RETURNING id
                    """
                ),
                {"name": name.strip(), "type": company_type.strip() or "B2B", "created_at": now},
            ).scalar_one()
        )


def issue_b2c_rental(engine, *, bike_id: int, client_id: int, planned_return_dt=None) -> int:
    ensure_rental_company_schema(engine)
    now = datetime.now()
    with engine.begin() as conn:
        client = conn.execute(
            text("SELECT id FROM client WHERE id = :client_id"),
            {"client_id": client_id},
        ).mappings().first()
        if not client:
            raise ValueError("Клиент не найден.")

        bike = conn.execute(
            text("SELECT id, serial_number, location_status, tech_status FROM bike WHERE id = :bike_id"),
            {"bike_id": bike_id},
        ).mappings().first()
        if not bike:
            raise ValueError("Велосипед не найден.")
        if bike.get("location_status") != "Свободен":
            raise ValueError(f"Велосипед {bike.get('serial_number') or bike_id} сейчас не свободен.")
        if bike.get("tech_status") != "Исправен":
            raise ValueError(f"Велосипед {bike.get('serial_number') or bike_id} нельзя выдать: техстатус '{bike.get('tech_status')}'.")

        active_rental = conn.execute(
            text("SELECT COUNT(*) FROM rental WHERE bike_id = :bike_id AND status = 'активна'"),
            {"bike_id": bike_id},
        ).scalar_one()
        if active_rental:
            raise ValueError("По этому велосипеду уже есть активная аренда.")

        conn.execute(
            text(
                """
                INSERT INTO rental (bike_id, client_id, company_id, start_dt, end_dt, days_count, status, created_at, updated_at)
                VALUES (:bike_id, :client_id, NULL, :start_dt, :end_dt, 0, 'активна', :created_at, :updated_at)
                """
            ),
            {
                "bike_id": bike_id,
                "client_id": client_id,
                "start_dt": now,
                "end_dt": planned_return_dt,
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.execute(
            text(
                """
                UPDATE bike
                SET location_status = 'В аренде',
                    holder_type = 'B2C',
                    holder_id = :client_id,
                    darkstore_id = NULL,
                    days_in_rent = 0,
                    updated_at = :updated_at
                WHERE id = :bike_id
                """
            ),
            {"client_id": client_id, "updated_at": now, "bike_id": bike_id},
        )
    return bike_id


def issue_b2b_rental(engine, *, bike_ids: list[int], company_id: int, darkstore_id: int) -> int:
    ensure_rental_company_schema(engine)
    now = datetime.now()
    with engine.begin() as conn:
        company = conn.execute(
            text("SELECT id, name FROM company WHERE id = :company_id"),
            {"company_id": company_id},
        ).mappings().first()
        if not company:
            raise ValueError("Компания не найдена.")
        darkstore = conn.execute(
            text("SELECT id, company_id, name FROM darkstore WHERE id = :darkstore_id"),
            {"darkstore_id": darkstore_id},
        ).mappings().first()
        if not darkstore:
            raise ValueError("Даркстор не найден.")
        if int(darkstore.get("company_id") or 0) != int(company_id):
            raise ValueError("Этот даркстор не принадлежит выбранной компании.")
        if not bike_ids:
            raise ValueError("Нужно выбрать хотя бы один велосипед.")

        inserted = 0
        for bike_id in bike_ids:
            bike = conn.execute(
                text("SELECT id, serial_number, location_status, tech_status FROM bike WHERE id = :bike_id"),
                {"bike_id": bike_id},
            ).mappings().first()
            if not bike:
                raise ValueError(f"Велосипед #{bike_id} не найден.")
            if bike.get("location_status") != "Свободен":
                raise ValueError(f"Велосипед {bike.get('serial_number') or bike_id} сейчас не свободен.")
            if bike.get("tech_status") != "Исправен":
                raise ValueError(f"Велосипед {bike.get('serial_number') or bike_id} нельзя выдать: техстатус '{bike.get('tech_status')}'.")
            active_rental = conn.execute(
                text("SELECT COUNT(*) FROM rental WHERE bike_id = :bike_id AND status = 'активна'"),
                {"bike_id": bike_id},
            ).scalar_one()
            if active_rental:
                raise ValueError(f"По велосипеду {bike.get('serial_number') or bike_id} уже есть активная аренда.")

            conn.execute(
                text(
                    """
                    INSERT INTO rental (bike_id, client_id, company_id, start_dt, end_dt, days_count, status, created_at, updated_at)
                    VALUES (:bike_id, NULL, :company_id, :start_dt, NULL, 0, 'активна', :created_at, :updated_at)
                    """
                ),
                {
                    "bike_id": bike_id,
                    "company_id": company_id,
                    "start_dt": now,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            conn.execute(
                text(
                    """
                    UPDATE bike
                    SET location_status = 'В аренде',
                        holder_type = 'B2B',
                        holder_id = :company_id,
                        darkstore_id = :darkstore_id,
                        days_in_rent = 0,
                        updated_at = :updated_at
                    WHERE id = :bike_id
                    """
                ),
                {"company_id": company_id, "darkstore_id": darkstore_id, "updated_at": now, "bike_id": bike_id},
            )
            inserted += 1
    return inserted


def ensure_workshop_repair(engine, *, bike_id: int, master_id: int) -> int:
    now = datetime.now()
    with engine.begin() as conn:
        existing = conn.execute(
            text(
                """
                WITH latest_assignment AS (
                    SELECT DISTINCT ON (repair_request_id)
                        repair_request_id,
                        assigned_to
                    FROM master_assignment
                    ORDER BY repair_request_id, assigned_at DESC, id DESC
                )
                SELECT rr.id
                FROM repair_request rr
                LEFT JOIN latest_assignment la ON la.repair_request_id = rr.id
                WHERE rr.bike_id = :bike_id
                  AND rr.type = 'внутренний ремонт'
                  AND rr.status IN ('назначена', 'в работе', 'отложена')
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
                text(
                    """
                    UPDATE repair_request
                    SET status = 'в работе',
                        updated_at = :updated_at
                    WHERE id = :repair_id
                    """
                ),
                {"updated_at": now, "repair_id": repair_id},
            )
        else:
            repair_id = conn.execute(
                text(
                    """
                    INSERT INTO repair_request (
                        bike_id,
                        incoming_id,
                        status,
                        type,
                        postponed_reason,
                        client_rating,
                        client_comment,
                        comment,
                        created_at,
                        updated_at
                    ) VALUES (
                        :bike_id,
                        NULL,
                        'в работе',
                        'внутренний ремонт',
                        NULL,
                        NULL,
                        NULL,
                        NULL,
                        :created_at,
                        :updated_at
                    )
                    RETURNING id
                    """
                ),
                {"bike_id": bike_id, "created_at": now, "updated_at": now},
            ).scalar_one()

            conn.execute(
                text(
                    """
                    INSERT INTO master_assignment (
                        repair_request_id,
                        assigned_by,
                        assigned_to,
                        comment,
                        assigned_at
                    ) VALUES (
                        :repair_request_id,
                        :assigned_by,
                        :assigned_to,
                        :comment,
                        :assigned_at
                    )
                    """
                ),
                {
                    "repair_request_id": repair_id,
                    "assigned_by": master_id,
                    "assigned_to": master_id,
                    "comment": "Мастер цеха взял велосипед в работу",
                    "assigned_at": now,
                },
            )

        conn.execute(
            text(
                """
                UPDATE bike
                SET tech_status = 'В ремонте',
                    updated_at = :updated_at
                WHERE id = :bike_id
                """
            ),
            {"updated_at": now, "bike_id": bike_id},
        )
    return int(repair_id)


def consume_storage_stock(engine, *, spare_part_catalog_id: int, repair_request_id: int, quantity: int) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        if quantity <= 0:
            raise ValueError("Количество должно быть больше нуля.")

        stock_rows = conn.execute(
            text(
                """
                SELECT id, quantity
                FROM spare_part_stock
                WHERE spare_part_catalog_id = :spare_part_catalog_id
                  AND quantity > 0
                ORDER BY quantity DESC, id ASC
                """
            ),
            {"spare_part_catalog_id": spare_part_catalog_id},
        ).mappings().all()

        total_available = sum(int(row.get("quantity") or 0) for row in stock_rows)
        if total_available < quantity:
            raise ValueError("На складе недостаточно этой запчасти.")

        remaining = quantity
        for row in stock_rows:
            if remaining <= 0:
                break
            available = int(row.get("quantity") or 0)
            take_qty = min(available, remaining)
            conn.execute(
                text(
                    """
                    UPDATE spare_part_stock
                    SET quantity = quantity - :quantity,
                        updated_at = :updated_at
                    WHERE id = :stock_id
                    """
                ),
                {"quantity": take_qty, "updated_at": now, "stock_id": row["id"]},
            )
            remaining -= take_qty

        existing_part = conn.execute(
            text(
                """
                SELECT id
                FROM repair_parts_used
                WHERE repair_request_id = :repair_request_id
                  AND spare_part_catalog_id = :spare_part_catalog_id
                """
            ),
            {"repair_request_id": repair_request_id, "spare_part_catalog_id": spare_part_catalog_id},
        ).mappings().first()

        if existing_part:
            conn.execute(
                text(
                    """
                    UPDATE repair_parts_used
                    SET quantity_used = quantity_used + :quantity
                    WHERE id = :id
                    """
                ),
                {"quantity": quantity, "id": existing_part["id"]},
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO repair_parts_used (
                        repair_request_id,
                        spare_part_catalog_id,
                        quantity_used,
                        created_at
                    ) VALUES (
                        :repair_request_id,
                        :spare_part_catalog_id,
                        :quantity_used,
                        :created_at
                    )
                    """
                ),
                {
                    "repair_request_id": repair_request_id,
                    "spare_part_catalog_id": spare_part_catalog_id,
                    "quantity_used": quantity,
                    "created_at": now,
                },
            )


def adjust_stock(engine, *, stock_id: int | None, spare_part_catalog_id: int, darkstore_id: int, delta: int) -> None:
    with engine.begin() as conn:
        if stock_id:
            conn.execute(
                text(
                    """
                    UPDATE spare_part_stock
                    SET quantity = quantity + :delta,
                        updated_at = :updated_at
                    WHERE id = :stock_id
                    """
                ),
                {"delta": delta, "updated_at": datetime.now(), "stock_id": stock_id},
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO spare_part_stock (
                        spare_part_catalog_id,
                        darkstore_id,
                        quantity,
                        updated_at
                    ) VALUES (
                        :spare_part_catalog_id,
                        :darkstore_id,
                        :quantity,
                        :updated_at
                    )
                    """
                ),
                {
                    "spare_part_catalog_id": spare_part_catalog_id,
                    "darkstore_id": darkstore_id,
                    "quantity": max(delta, 0),
                    "updated_at": datetime.now(),
                },
            )


def transfer_stock_to_master(engine, *, stock_id: int, master_id: int, quantity: int) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        stock_row = conn.execute(
            text(
                """
                SELECT id, spare_part_catalog_id, darkstore_id, quantity
                FROM spare_part_stock
                WHERE id = :stock_id
                """
            ),
            {"stock_id": stock_id},
        ).mappings().first()
        if not stock_row:
            raise ValueError("Складская позиция не найдена.")
        if quantity <= 0:
            raise ValueError("Количество должно быть больше нуля.")
        if int(stock_row["quantity"] or 0) < quantity:
            raise ValueError("На складе недостаточно запчастей.")

        conn.execute(
            text(
                """
                UPDATE spare_part_stock
                SET quantity = quantity - :quantity,
                    updated_at = :updated_at
                WHERE id = :stock_id
                """
            ),
            {"quantity": quantity, "updated_at": now, "stock_id": stock_id},
        )

        master_row = conn.execute(
            text(
                """
                SELECT id
                FROM master_spare_stock
                WHERE master_id = :master_id
                  AND spare_part_catalog_id = :spare_part_catalog_id
                """
            ),
            {"master_id": master_id, "spare_part_catalog_id": stock_row["spare_part_catalog_id"]},
        ).mappings().first()

        if master_row:
            conn.execute(
                text(
                    """
                    UPDATE master_spare_stock
                    SET quantity = quantity + :quantity,
                        updated_at = :updated_at
                    WHERE id = :id
                    """
                ),
                {"quantity": quantity, "updated_at": now, "id": master_row["id"]},
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO master_spare_stock (
                        master_id,
                        spare_part_catalog_id,
                        quantity,
                        picked_at,
                        updated_at
                    ) VALUES (
                        :master_id,
                        :spare_part_catalog_id,
                        :quantity,
                        :picked_at,
                        :updated_at
                    )
                    """
                ),
                {
                    "master_id": master_id,
                    "spare_part_catalog_id": stock_row["spare_part_catalog_id"],
                    "quantity": quantity,
                    "picked_at": now,
                    "updated_at": now,
                },
            )


def return_master_stock_to_storage(engine, *, master_stock_id: int, quantity: int, stock_id: int | None = None, darkstore_id: int | None = None) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        master_row = conn.execute(
            text(
                """
                SELECT id, master_id, spare_part_catalog_id, quantity
                FROM master_spare_stock
                WHERE id = :master_stock_id
                """
            ),
            {"master_stock_id": master_stock_id},
        ).mappings().first()
        if not master_row:
            raise ValueError("Позиция в багажнике не найдена.")
        if quantity <= 0:
            raise ValueError("Количество должно быть больше нуля.")
        if int(master_row["quantity"] or 0) < quantity:
            raise ValueError("В багажнике мастера недостаточно запчастей.")

        conn.execute(
            text(
                """
                UPDATE master_spare_stock
                SET quantity = quantity - :quantity,
                    updated_at = :updated_at
                WHERE id = :id
                """
            ),
            {"quantity": quantity, "updated_at": now, "id": master_row["id"]},
        )

        if stock_id:
            stock_row = conn.execute(
                text(
                    """
                    SELECT id
                    FROM spare_part_stock
                    WHERE id = :stock_id
                    """
                ),
                {"stock_id": stock_id},
            ).mappings().first()
        else:
            stock_row = conn.execute(
                text(
                    """
                    SELECT id
                    FROM spare_part_stock
                    WHERE darkstore_id = :darkstore_id
                      AND spare_part_catalog_id = :spare_part_catalog_id
                    """
                ),
                {"darkstore_id": darkstore_id, "spare_part_catalog_id": master_row["spare_part_catalog_id"]},
            ).mappings().first()

        if stock_row:
            conn.execute(
                text(
                    """
                    UPDATE spare_part_stock
                    SET quantity = quantity + :quantity,
                        updated_at = :updated_at
                    WHERE id = :id
                    """
                ),
                {"quantity": quantity, "updated_at": now, "id": stock_row["id"]},
            )
        elif darkstore_id is not None:
            conn.execute(
                text(
                    """
                    INSERT INTO spare_part_stock (
                        spare_part_catalog_id,
                        darkstore_id,
                        quantity,
                        updated_at
                    ) VALUES (
                        :spare_part_catalog_id,
                        :darkstore_id,
                        :quantity,
                        :updated_at
                    )
                    """
                ),
                {
                    "spare_part_catalog_id": master_row["spare_part_catalog_id"],
                    "darkstore_id": darkstore_id,
                    "quantity": quantity,
                    "updated_at": now,
                },
            )


def consume_master_stock(engine, *, master_stock_id: int, repair_request_id: int, quantity: int) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        master_row = conn.execute(
            text(
                """
                SELECT id, spare_part_catalog_id, quantity
                FROM master_spare_stock
                WHERE id = :master_stock_id
                """
            ),
            {"master_stock_id": master_stock_id},
        ).mappings().first()
        if not master_row:
            raise ValueError("Позиция в багажнике не найдена.")
        if quantity <= 0:
            raise ValueError("Количество должно быть больше нуля.")
        if int(master_row["quantity"] or 0) < quantity:
            raise ValueError("В багажнике недостаточно запчастей.")

        conn.execute(
            text(
                """
                UPDATE master_spare_stock
                SET quantity = quantity - :quantity,
                    updated_at = :updated_at
                WHERE id = :id
                """
            ),
            {"quantity": quantity, "updated_at": now, "id": master_row["id"]},
        )

        existing_part = conn.execute(
            text(
                """
                SELECT id
                FROM repair_parts_used
                WHERE repair_request_id = :repair_request_id
                  AND spare_part_catalog_id = :spare_part_catalog_id
                """
            ),
            {
                "repair_request_id": repair_request_id,
                "spare_part_catalog_id": master_row["spare_part_catalog_id"],
            },
        ).mappings().first()

        if existing_part:
            conn.execute(
                text(
                    """
                    UPDATE repair_parts_used
                    SET quantity_used = quantity_used + :quantity
                    WHERE id = :id
                    """
                ),
                {"quantity": quantity, "id": existing_part["id"]},
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO repair_parts_used (
                        repair_request_id,
                        spare_part_catalog_id,
                        quantity_used,
                        created_at
                    ) VALUES (
                        :repair_request_id,
                        :spare_part_catalog_id,
                        :quantity_used,
                        :created_at
                    )
                    """
                ),
                {
                    "repair_request_id": repair_request_id,
                    "spare_part_catalog_id": master_row["spare_part_catalog_id"],
                    "quantity_used": quantity,
                    "created_at": now,
                },
            )


def transfer_catalog_stock_to_master(engine, *, spare_part_catalog_id: int, master_id: int, quantity: int) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        if quantity <= 0:
            raise ValueError("Количество должно быть больше нуля.")

        stock_rows = conn.execute(
            text(
                """
                SELECT id, quantity
                FROM spare_part_stock
                WHERE spare_part_catalog_id = :spare_part_catalog_id
                  AND quantity > 0
                ORDER BY quantity DESC, id ASC
                """
            ),
            {"spare_part_catalog_id": spare_part_catalog_id},
        ).mappings().all()

        total_available = sum(int(row.get("quantity") or 0) for row in stock_rows)
        if total_available < quantity:
            raise ValueError("На складе недостаточно запчастей для перевода мастеру.")

        remaining = quantity
        for row in stock_rows:
            if remaining <= 0:
                break
            available = int(row.get("quantity") or 0)
            move_qty = min(available, remaining)
            conn.execute(
                text(
                    """
                    UPDATE spare_part_stock
                    SET quantity = quantity - :quantity,
                        updated_at = :updated_at
                    WHERE id = :stock_id
                    """
                ),
                {"quantity": move_qty, "updated_at": now, "stock_id": row["id"]},
            )
            remaining -= move_qty

        master_row = conn.execute(
            text(
                """
                SELECT id
                FROM master_spare_stock
                WHERE master_id = :master_id
                  AND spare_part_catalog_id = :spare_part_catalog_id
                """
            ),
            {"master_id": master_id, "spare_part_catalog_id": spare_part_catalog_id},
        ).mappings().first()

        if master_row:
            conn.execute(
                text(
                    """
                    UPDATE master_spare_stock
                    SET quantity = quantity + :quantity,
                        updated_at = :updated_at
                    WHERE id = :id
                    """
                ),
                {"quantity": quantity, "updated_at": now, "id": master_row["id"]},
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO master_spare_stock (
                        master_id,
                        spare_part_catalog_id,
                        quantity,
                        picked_at,
                        updated_at
                    ) VALUES (
                        :master_id,
                        :spare_part_catalog_id,
                        :quantity,
                        :picked_at,
                        :updated_at
                    )
                    """
                ),
                {
                    "master_id": master_id,
                    "spare_part_catalog_id": spare_part_catalog_id,
                    "quantity": quantity,
                    "picked_at": now,
                    "updated_at": now,
                },
            )


def aggregate_stock_by_part(stock_rows: list[dict]) -> list[dict]:
    aggregated: dict[int, dict] = {}
    for row in stock_rows:
        catalog_id = row.get("spare_part_catalog_id")
        if catalog_id is None:
            continue
        item = aggregated.setdefault(
            int(catalog_id),
            {
                "spare_part_catalog_id": int(catalog_id),
                "spare_name": row.get("spare_name") or "Запчасть",
                "article": row.get("article") or "",
                "quantity": 0,
                "stock_rows": [],
            },
        )
        item["quantity"] += int(row.get("quantity") or 0)
        item["stock_rows"].append(row)
    return sorted(aggregated.values(), key=lambda item: ((item.get("spare_name") or "").lower(), item["spare_part_catalog_id"]))


@st.cache_data(ttl=60)
def load_master_spare_stock(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    mss.id,
                    mss.master_id,
                    mss.spare_part_catalog_id,
                    mss.quantity,
                    mss.picked_at,
                    mss.updated_at,
                    spc.article,
                    spc.name AS spare_name,
                    e.first_name,
                    e.last_name
                FROM master_spare_stock mss
                LEFT JOIN spare_part_catalog spc ON spc.id = mss.spare_part_catalog_id
                LEFT JOIN employee e ON e.id = mss.master_id
                ORDER BY e.last_name, e.first_name, spc.name
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_darkstores(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, name, direction, latitude, longitude, company_id
                FROM darkstore
                ORDER BY name
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_employees(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, first_name, last_name, role
                FROM employee
                ORDER BY role, last_name, first_name
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_clients(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, type, name, phone, darkstore_id
                FROM client
                ORDER BY type, name
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_companies(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, name, type, created_at
                FROM company
                ORDER BY name
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_rentals(_engine):
    ensure_rental_company_schema(_engine)
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    r.id,
                    r.bike_id,
                    r.client_id,
                    r.company_id,
                    r.start_dt,
                    r.end_dt,
                    r.days_count,
                    r.status,
                    r.created_at,
                    r.updated_at,
                    c.name AS client_name,
                    c.type AS client_type,
                    c.darkstore_id AS client_darkstore_id,
                    co.name AS company_name,
                    co.type AS company_type,
                    b.serial_number,
                    b.gov_number,
                    b.darkstore_id,
                    ds.name AS darkstore_name,
                    ds.direction AS darkstore_direction
                FROM rental r
                LEFT JOIN client c ON c.id = r.client_id
                LEFT JOIN company co ON co.id = r.company_id
                LEFT JOIN bike b ON b.id = r.bike_id
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
                    b.id,
                    b.serial_number,
                    b.gov_number,
                    b.model,
                    b.location_status,
                    b.tech_status,
                    b.holder_type,
                    b.holder_id,
                    b.darkstore_id,
                    b.days_in_rent,
                    b.iot_device_id,
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
def load_incoming_requests(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                WITH latest_assignment AS (
                    SELECT DISTINCT ON (repair_request_id)
                        repair_request_id,
                        assigned_to,
                        assigned_at
                    FROM master_assignment
                    ORDER BY repair_request_id, assigned_at DESC, id DESC
                )
                SELECT
                    ir.id,
                    ir.request_type,
                    ir.device_type,
                    ir.direction,
                    ir.darkstore_id,
                    ir.bike_id,
                    ir.problem,
                    ir.status,
                    ir.curator_name,
                    ir.full_address,
                    ir.created_at,
                    ir.updated_at,
                    b.serial_number,
                    b.gov_number,
                    b.model,
                    b.iot_device_id,
                    b.tech_status,
                    b.location_status,
                    ds.name AS darkstore_name,
                    ds.direction AS darkstore_direction,
                    la.assigned_to,
                    e.first_name AS assigned_first_name,
                    e.last_name AS assigned_last_name
                FROM incoming_request ir
                LEFT JOIN bike b ON b.id = ir.bike_id
                LEFT JOIN darkstore ds ON ds.id = ir.darkstore_id
                LEFT JOIN repair_request rr ON rr.incoming_id = ir.id
                LEFT JOIN latest_assignment la ON la.repair_request_id = rr.id
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
                        repair_request_id,
                        assigned_to,
                        assigned_by,
                        comment,
                        assigned_at
                    FROM master_assignment
                    ORDER BY repair_request_id, assigned_at DESC, id DESC
                )
                SELECT
                    rr.id,
                    rr.bike_id,
                    rr.incoming_id,
                    rr.status,
                    rr.type,
                    rr.postponed_reason,
                    rr.client_rating,
                    rr.client_comment,
                    rr.comment,
                    rr.created_at,
                    rr.updated_at,
                    ir.problem,
                    ir.device_type,
                    ir.request_type,
                    ir.darkstore_id,
                    ir.full_address,
                    b.serial_number,
                    b.gov_number,
                    b.model,
                    b.iot_device_id,
                    b.tech_status,
                    b.location_status,
                    b.holder_type,
                    ds.name AS darkstore_name,
                    ds.direction AS darkstore_direction,
                    ds.latitude AS darkstore_latitude,
                    ds.longitude AS darkstore_longitude,
                    la.assigned_to,
                    la.comment AS assignment_comment,
                    la.assigned_at,
                    e.first_name,
                    e.last_name,
                    e.role AS employee_role
                FROM repair_request rr
                LEFT JOIN incoming_request ir ON ir.id = rr.incoming_id
                LEFT JOIN bike b ON b.id = rr.bike_id
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
                    sps.id,
                    sps.spare_part_catalog_id,
                    sps.darkstore_id,
                    sps.quantity,
                    sps.updated_at,
                    spc.article,
                    spc.name AS spare_name,
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
            text(
                """
                SELECT id, article, name, description
                FROM spare_part_catalog
                ORDER BY name
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]


@st.cache_data(ttl=60)
def load_parts_used(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    rpu.id,
                    rpu.repair_request_id,
                    rpu.spare_part_catalog_id,
                    rpu.quantity_used,
                    rpu.created_at,
                    spc.article,
                    spc.name AS spare_name,
                    rr.type AS repair_type,
                    rr.status AS repair_status,
                    rr.bike_id,
                    rr.incoming_id
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
            text(
                """
                SELECT id, name, default_spare_parts
                FROM work_type
                ORDER BY name
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
                        repair_request_id,
                        assigned_to
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
                    e.id,
                    e.first_name,
                    e.last_name,
                    e.role,
                    COALESCE(AVG(d.repairs_done), 0) AS avg_repairs_per_day,
                    COALESCE(SUM(d.repairs_done), 0) AS total_repairs,
                    COALESCE(COUNT(d.work_day), 0) AS shift_days
                FROM employee e
                LEFT JOIN daily d ON d.employee_id = e.id
                GROUP BY e.id, e.first_name, e.last_name, e.role
                ORDER BY e.role, e.last_name, e.first_name
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]


def metric_card(label: str, value: str, note: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{html.escape(label)}</div>
            <div class="metric-value">{html.escape(value)}</div>
            <div class="metric-note">{html.escape(note)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def badge_class(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"новая", "назначена", "в работе", "ожидает выездного ремонта", "в ремонте"}:
        return "chip-red"
    if normalized in {"отложена", "ожидает запчасти", "замена_вело", "замена вело"}:
        return "chip-soft-red"
    if normalized in {"завершена", "исправен", "свободен"}:
        return "chip-dark"
    return "chip-default"


def status_chip(value: str) -> str:
    safe_value = html.escape(str(value or "—"))
    return f'<span class="chip {badge_class(value)}">{safe_value}</span>'


def render_record_card(title: str, subtitle: str, status: str, fields: list[tuple[str, str]]) -> None:
    fields_html = "".join(
        f"""
        <div class="record-field">
            <div class="record-field-label">{html.escape(str(label))}</div>
            <div class="record-field-value">{html.escape(str(value))}</div>
        </div>
        """
        for label, value in fields
        if value not in (None, "", "None")
    )
    st.markdown(
        f"""
        <div class="record-card">
            <div class="record-top">
                <div>
                    <div class="record-title">{html.escape(str(title))}</div>
                    <div class="record-subtitle">{html.escape(str(subtitle))}</div>
                </div>
                {status_chip(status)}
            </div>
            <div class="record-grid">{fields_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_pills(items: dict[str, int], red_keys: tuple[str, ...] = ()) -> None:
    if not items:
        return
    chunks = []
    for key, value in items.items():
        css = "pill red" if key in red_keys else "pill"
        chunks.append(f'<span class="{css}">{html.escape(str(key))}: {value}</span>')
    st.markdown(f'<div class="pill-row">{"".join(chunks)}</div>', unsafe_allow_html=True)


def render_empty(message: str) -> None:
    st.markdown(f'<div class="empty">{html.escape(message)}</div>', unsafe_allow_html=True)


def count_by(rows: list[dict], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = row.get(key) or "—"
        result[value] = result.get(value, 0) + 1
    return result


def compact_request_card(row: dict) -> None:
    title = f"#{row['id']} · {row.get('device_type') or 'Велосипед'}"
    subtitle = f"{row.get('darkstore_name') or '—'} · {format_short_date(row.get('created_at'))}"
    fields = [
        ("Гос номер", row.get("gov_number") or "—"),
        ("Модель", row.get("model") or "—"),
        ("Проблема", row.get("problem") or "—"),
        ("Мастер", latest_assignment_name(row)),
    ]
    render_record_card(title=title, subtitle=subtitle, status=row.get("status") or "—", fields=fields)


def compact_repair_card(row: dict) -> None:
    title = f"Repair #{row['id']} · {row.get('type') or '—'}"
    subtitle = f"{row.get('darkstore_name') or '—'} · {latest_assignment_name(row)}"
    fields = [
        ("Гос номер", row.get("gov_number") or "—"),
        ("Проблема", row.get("problem") or "—"),
        ("Запрос", f"#{row.get('incoming_id')}" if row.get("incoming_id") else "Внутренний"),
        ("Обновлено", format_dt(row.get("updated_at"))),
    ]
    render_record_card(title=title, subtitle=subtitle, status=row.get("status") or "—", fields=fields)


def field_master_status_rank(status: str) -> int:
    order = {
        "назначена": 0,
        "в работе": 1,
        "отложена": 2,
        "ожидает запчасти": 2,
        "замена вело": 3,
        "завершена": 4,
    }
    return order.get((status or "").strip().lower(), 9)


def sort_field_master_repairs(rows: list[dict]) -> list[dict]:
    return sorted(
        rows,
        key=lambda row: (
            field_master_status_rank(row.get("status")),
            row.get("darkstore_direction") or "",
            row.get("darkstore_name") or "",
            row.get("updated_at") or datetime.min,
        ),
    )


def suggested_spare_parts_for_repair(repair: dict, spare_catalog: list[dict]) -> list[dict]:
    problem = f"{repair.get('problem') or ''} {repair.get('comment') or ''}".lower()
    suggestions = []
    keyword_map = {
        "торм": ("тормоз", "колод"),
        "цеп": ("цеп",),
        "кам": ("камер",),
        "аккум": ("акб", "аккум"),
        "мотор": ("мотор",),
    }
    for part in spare_catalog:
        haystack = f"{part.get('name') or ''} {part.get('article') or ''} {part.get('description') or ''}".lower()
        matched = False
        for _, keywords in keyword_map.items():
            if any(keyword in problem for keyword in keywords) and any(keyword in haystack for keyword in keywords):
                matched = True
                break
        if matched:
            suggestions.append(part)
    if not suggestions and spare_catalog:
        suggestions = spare_catalog[:3]
    return suggestions[:5]


def build_yandex_maps_link(route_points: list[dict]) -> str:
    if not route_points:
        return ""
    base = "https://yandex.ru/maps/?rtext="
    points = "~".join(f"{point['lat']},{point['lon']}" for point in route_points)
    return f"{base}{points}&rtt=auto"


def bike_history_for_darkstore(bike_id: int, darkstore_id: int, incoming_requests: list[dict]) -> list[dict]:
    rows = [row for row in incoming_requests if row.get("bike_id") == bike_id and row.get("darkstore_id") == darkstore_id]
    return sorted(rows, key=lambda row: row.get("created_at") or datetime.min, reverse=True)


def bike_logs_for_bike(bike_id: int, bike_logs: list[dict]) -> list[dict]:
    return [row for row in bike_logs if row.get("bike_id") == bike_id]


def filter_bikes(bikes: list[dict], search: str, fields: tuple[str, ...]) -> list[dict]:
    if not search:
        return bikes
    needle = search.strip().lower()
    result = []
    for bike in bikes:
        haystack = " ".join(str(bike.get(field) or "") for field in fields).lower()
        if needle in haystack:
            result.append(bike)
    return result


def latest_assignment_name(row: dict) -> str:
    first_name = (row.get("assigned_first_name") or row.get("first_name") or "").strip()
    last_name = (row.get("assigned_last_name") or row.get("last_name") or "").strip()
    name = f"{last_name} {first_name}".strip()
    return name or "—"


def role_hero(title: str, subtitle: str, context: str, note: str) -> None:
    st.markdown(
        f"""
        <div class="hero">
            <div class="hero-eyebrow">Vanta ERP · Role Workspace</div>
            <div class="hero-title">{html.escape(title)}</div>
            <div class="hero-subtitle">{html.escape(subtitle)}</div>
            <div class="hero-context">{html.escape(context)}</div>
            <div class="hero-note">{html.escape(note)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_switcher(key: str, options: list[str]) -> str:
    return st.radio("Раздел", options, key=key, horizontal=True, label_visibility="collapsed")


def build_curator_bike_label(bike: dict, open_request_bike_ids: set[int]) -> str:
    parts = [
        bike.get("gov_number") or "Без гос номера",
        bike.get("serial_number") or f"Bike #{bike['id']}",
        bike.get("tech_status") or "—",
    ]
    if bike["id"] in open_request_bike_ids:
        parts.append("уже есть заявка")
    return " · ".join(parts)


def curator_dashboard(darkstore: dict, incoming_requests: list[dict], bikes: list[dict], bike_logs: list[dict], engine) -> None:
    ds_requests = [row for row in incoming_requests if row.get("darkstore_id") == darkstore["id"]]
    ds_bikes = [row for row in bikes if row.get("darkstore_id") == darkstore["id"]]
    open_requests = [row for row in ds_requests if row.get("status") not in DONE_REQUEST_STATUSES]
    open_request_bike_ids = {
        row.get("bike_id")
        for row in ds_requests
        if row.get("status") not in DONE_REQUEST_STATUSES and row.get("bike_id")
    }

    context = f"Даркстор {darkstore.get('name')} · направление {darkstore.get('direction') or 'не указано'}"
    note = "Куратор видит только свой парк, свои заявки и действия по созданию новой заявки."
    role_hero("Куратор / Даркстор", "Рабочее место для контроля парка и заявок по одной точке.", context, note)

    left, right = st.columns(2)
    with left:
        metric_card("Велосипедов в парке", str(len(ds_bikes)), "Все велосипеды этого даркстора")
    with right:
        metric_card("Заявок висит", str(len(open_requests)), "Новые, назначенные и в работе")

    screen = section_switcher("curator_section", ["Мой парк", "Мои заявки", "Создать заявку"])

    if screen == "Мой парк":
        st.markdown('<div class="section-title">Мой парк</div>', unsafe_allow_html=True)
        with st.form("curator_search_form", clear_on_submit=False):
            search = st.text_input("Поиск велосипеда по гос номеру", placeholder="Например, А123ВС")
            submitted = st.form_submit_button("Найти")
        if submitted:
            st.session_state["curator_bike_search"] = search
        search_value = st.session_state.get("curator_bike_search", "")
        filtered = filter_bikes(ds_bikes, search_value, ("gov_number",))
        render_pills(count_by(filtered, "tech_status"), red_keys=("Ожидает выездного ремонта", "В ремонте", "Ожидает запчасти"))

        if not filtered:
            render_empty("По этому фильтру велосипеды не найдены.")

        for bike in filtered:
            title = bike.get("gov_number") or bike.get("serial_number") or f"Bike #{bike['id']}"
            subtitle = f"{darkstore.get('name')} · {darkstore.get('direction') or 'без направления'}"
            render_record_card(
                title=title,
                subtitle=subtitle,
                status=bike.get("tech_status") or "—",
                fields=[
                    ("IoT", bike.get("iot_device_id") or "—"),
                    ("Серийный номер", bike.get("serial_number") or "—"),
                    ("Модель", bike.get("model") or "—"),
                    ("Дней на дарке", bike.get("days_in_rent") or 0),
                    ("Тех статус", bike.get("tech_status") or "—"),
                    ("Статус локации", bike.get("location_status") or "—"),
                ],
            )
            with st.expander("Карточка велосипеда"):
                history = bike_history_for_darkstore(bike["id"], darkstore["id"], incoming_requests)
                st.markdown("**История заявок с этого дарка**")
                if history:
                    for row in history:
                        st.markdown(f"- `#{row['id']}` · {row.get('status') or '—'} · {format_dt(row.get('created_at'))} · {row.get('problem') or 'Без описания'}")
                else:
                    render_empty("По этому велосипеду с данного даркстора еще не было заявок.")

                st.markdown("**Последние изменения велосипеда**")
                logs = bike_logs_for_bike(bike["id"], bike_logs)
                if logs:
                    for row in logs[:5]:
                        actor = latest_assignment_name(row)
                        st.markdown(f"- `{row.get('action')}`: {row.get('old_value') or '—'} → {row.get('new_value') or '—'} · {actor}")
                else:
                    render_empty("Логов по велосипеду пока нет.")

                if bike["id"] in open_request_bike_ids:
                    st.info("По этому велосипеду уже есть активная заявка.")
                else:
                    if st.button("Составить заявку на ремонт", key=f"curator_from_bike_{bike['id']}", use_container_width=True):
                        st.session_state["curator_prefill_bike_id"] = bike["id"]
                        st.session_state["curator_section"] = "Создать заявку"
                        st.rerun()

    elif screen == "Мои заявки":
        st.markdown('<div class="section-title">Мои заявки</div>', unsafe_allow_html=True)
        render_pills(count_by(ds_requests, "status"), red_keys=("новая", "назначена", "в работе"))
        if not ds_requests:
            render_empty("По этому даркстору пока нет заявок.")

        for row in ds_requests:
            render_record_card(
                title=f"Заявка #{row['id']}",
                subtitle=f"{format_dt(row.get('created_at'))} · устройство: {row.get('device_type') or row.get('request_type') or '—'}",
                status=row.get("status") or "—",
                fields=[
                    ("Тип устройства", row.get("device_type") or "Велосипед"),
                    ("Гос номер", row.get("gov_number") or "—"),
                    ("Модель", row.get("model") or "—"),
                    ("Проблема", row.get("problem") or "—"),
                    ("Назначена на", latest_assignment_name(row)),
                    ("Создана", format_dt(row.get("created_at"))),
                ],
            )
            with st.expander("Открыть заявку"):
                st.markdown(f"**Создана:** {format_dt(row.get('created_at'))}")
                st.markdown(f"**Полный адрес:** {row.get('full_address') or '—'}")
                st.markdown(f"**Велосипед:** {row.get('serial_number') or '—'}")
                st.markdown(f"**Назначена на:** {latest_assignment_name(row)}")
                if row.get("status") == "новая":
                    st.caption("Новая заявка еще не назначена мастеру.")

    else:
        st.markdown('<div class="section-title">Создать заявку</div>', unsafe_allow_html=True)
        prefilled_bike_id = st.session_state.pop("curator_prefill_bike_id", None)
        bike_options = {build_curator_bike_label(bike, open_request_bike_ids): bike["id"] for bike in ds_bikes}
        prefilled_label = next((label for label, bike_id in bike_options.items() if bike_id == prefilled_bike_id), None)

        with st.form("curator_create_request_form", clear_on_submit=True):
            device_type = st.selectbox("Тип устройства", ["Велосипед", "Аккумулятор", "Зарядное устройство"], index=0)
            bike_label = None
            if device_type == "Велосипед":
                labels = list(bike_options.keys())
                default_index = labels.index(prefilled_label) if prefilled_label in labels else 0
                bike_label = st.selectbox("Велосипед", labels, index=default_index if labels else None)
            problem = st.text_area("Опишите проблему", height=120, placeholder="Что именно не работает или требует выезда мастера?")
            full_address = st.text_input("Адрес / комментарий для точки", value=darkstore.get("name") or "")
            st.file_uploader("Фото", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
            submitted = st.form_submit_button("Создать заявку", type="primary", use_container_width=True)

        if submitted:
            try:
                if not problem.strip():
                    raise ValueError("Нужно описать проблему.")
                bike_id = bike_options.get(bike_label) if device_type == "Велосипед" and bike_label else None
                create_incoming_request(
                    engine,
                    darkstore=darkstore,
                    device_type=device_type,
                    bike_id=bike_id,
                    problem=problem.strip(),
                    full_address=full_address.strip(),
                )
                refresh_all_caches()
                flash_success("Заявка успешно создана.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def dispatcher_dashboard(
    current_user: dict,
    incoming_requests: list[dict],
    repairs: list[dict],
    bikes: list[dict],
    employees: list[dict],
    productivity: list[dict],
    parts_used: list[dict],
    engine,
) -> None:
    field_masters = [row for row in employees if row.get("role") in EMPLOYEE_ROLE_MAP["field_master"]]
    field_master_ids = {row["id"] for row in field_masters}
    field_master_repairs = [row for row in repairs if row.get("assigned_to") in field_master_ids]
    repair_by_incoming = {row.get("incoming_id"): row for row in repairs if row.get("incoming_id")}

    status_counts = {
        "новые": len([row for row in incoming_requests if row.get("status") == "новая"]),
        "назначены": len([row for row in incoming_requests if row.get("status") == "назначена"]),
        "в работе": len([row for row in incoming_requests if row.get("status") == "в работе"]),
        "ожидают": len([row for row in incoming_requests if row.get("status") in {"отложена", "ожидает запчасти"}]),
        "завершены": len([row for row in incoming_requests if row.get("status") == "завершена"]),
        "вывозов планируется": len([row for row in incoming_requests if row.get("request_type") == "вывоз"]) + len([row for row in repairs if row.get("type") == "вывоз"]),
    }

    direction_counts = count_by(incoming_requests, "direction")
    darkstore_removal_counts: dict[str, int] = {}
    for row in incoming_requests:
        if row.get("request_type") == "вывоз" or (repair_by_incoming.get(row["id"]) and repair_by_incoming[row["id"]].get("type") == "вывоз"):
            key = row.get("darkstore_name") or "Без даркстора"
            darkstore_removal_counts[key] = darkstore_removal_counts.get(key, 0) + 1

    master_workload: dict[str, int] = {}
    for row in field_master_repairs:
        if row.get("status") in ACTIVE_MASTER_STATUSES or row.get("status") == "завершена":
            master_name = latest_assignment_name(row)
            master_workload[master_name] = master_workload.get(master_name, 0) + 1

    field_productivity = [row for row in productivity if row.get("id") in field_master_ids]
    productivity_map = {full_name(row): row for row in field_productivity}

    parts_by_master: dict[str, int] = {}
    parts_by_darkstore: dict[str, int] = {}
    part_names: dict[str, int] = {}
    repair_map = {row["id"]: row for row in repairs}
    for row in parts_used:
        repair = repair_map.get(row.get("repair_request_id"))
        if not repair or repair.get("assigned_to") not in field_master_ids:
            continue
        qty = int(row.get("quantity_used") or 0)
        master_name = latest_assignment_name(repair)
        darkstore_name = repair.get("darkstore_name") or "Без даркстора"
        spare_name = row.get("spare_name") or row.get("article") or "Запчасть"
        parts_by_master[master_name] = parts_by_master.get(master_name, 0) + qty
        parts_by_darkstore[darkstore_name] = parts_by_darkstore.get(darkstore_name, 0) + qty
        part_names[spare_name] = part_names.get(spare_name, 0) + qty

    ratings = [float(row.get("client_rating")) for row in field_master_repairs if row.get("client_rating") is not None]
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else 0

    role_hero(
        "Диспетчер",
        "Дашборд входящего потока, фильтрация заявок и контроль работ по выездным мастерам.",
        f"Текущий пользователь: {full_name(current_user)}",
        "Здесь собраны входящие заявки, нагрузка по направлениям и мастерам, расход запчастей и планируемые вывозы.",
    )

    top = st.columns(6)
    for column, (label, value) in zip(top, status_counts.items()):
        with column:
            metric_card(label, str(value), "Поток заявок")

    st.markdown('<div class="section-title">Аналитика диспетчера</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-caption">Нагрузка по направлениям, мастерам, вывозам, продуктивности и расходу запчастей только по выездному контуру.</div>', unsafe_allow_html=True)

    analytics_left, analytics_right = st.columns(2)
    with analytics_left:
        render_record_card(
            title="Заявки по направлениям",
            subtitle="Сколько входящих заявок по каждому направлению",
            status=f"{sum(direction_counts.values())} всего",
            fields=[(direction, count) for direction, count in sorted(direction_counts.items(), key=lambda item: (-item[1], item[0]))[:6]],
        )
        render_record_card(
            title="Нагрузка по мастерам",
            subtitle="Сколько заявок сейчас закреплено за каждым выездным мастером",
            status=f"{len(field_masters)} мастеров",
            fields=[(name, count) for name, count in sorted(master_workload.items(), key=lambda item: (-item[1], item[0]))[:6]] or [("Нет данных", "0")],
        )
        render_record_card(
            title="Планируемые вывозы / замены",
            subtitle="Сколько специальных кейсов на каждом дарксторе",
            status=f"{sum(darkstore_removal_counts.values())} кейсов",
            fields=[(name, count) for name, count in sorted(darkstore_removal_counts.items(), key=lambda item: (-item[1], item[0]))[:6]] or [("Нет вывозов", "0")],
        )
    with analytics_right:
        render_record_card(
            title="Продуктивность выездных",
            subtitle="Средняя выработка по завершенным работам",
            status=f"{len(field_productivity)} сотрудников",
            fields=[
                (name, f"{float(row.get('avg_repairs_per_day') or 0):.1f} / день")
                for name, row in sorted(productivity_map.items(), key=lambda item: (-float(item[1].get("avg_repairs_per_day") or 0), item[0]))[:6]
            ] or [("Нет данных", "0")],
        )
        render_record_card(
            title="Расход запчастей",
            subtitle="Сколько запчастей списано по выездным мастерам",
            status=f"{sum(parts_by_master.values())} шт.",
            fields=[(name, qty) for name, qty in sorted(parts_by_master.items(), key=lambda item: (-item[1], item[0]))[:6]] or [("Нет списаний", "0")],
        )
        render_record_card(
            title="Оценка ремонтов",
            subtitle="Средняя клиентская оценка и самые частые запчасти",
            status=f"{avg_rating:.2f}" if ratings else "Нет оценок",
            fields=([("Средняя оценка", avg_rating), ("Оценок", len(ratings))] + [(name, qty) for name, qty in sorted(part_names.items(), key=lambda item: (-item[1], item[0]))[:4]])[:6],
        )

    section = section_switcher("dispatcher_section", ["Поток заявок", "Работы выездных"])

    if section == "Поток заявок":
        st.markdown('<div class="section-title">Поток заявок</div>', unsafe_allow_html=True)
        filter_cols = st.columns(4)
        status_options = ["Все"] + sorted({row.get("status") or "—" for row in incoming_requests})
        direction_options = ["Все"] + sorted({row.get("direction") or "—" for row in incoming_requests})
        type_options = ["Все"] + sorted({row.get("request_type") or "—" for row in incoming_requests})
        master_options = ["Все"] + sorted({latest_assignment_name(row) for row in incoming_requests})

        selected_status = filter_cols[0].selectbox("Статус", status_options, key="dispatcher_filter_status")
        selected_direction = filter_cols[1].selectbox("Направление", direction_options, key="dispatcher_filter_direction")
        selected_type = filter_cols[2].selectbox("Тип заявки", type_options, key="dispatcher_filter_type")
        selected_master = filter_cols[3].selectbox("Мастер", master_options, key="dispatcher_filter_master")
        search = st.text_input("Поиск по номеру заявки, гос номеру, даркстору или проблеме", placeholder="Например, А101АА или 1234")

        filtered_requests = []
        for row in incoming_requests:
            haystack = " ".join(
                [
                    str(row.get("id") or ""),
                    str(row.get("gov_number") or ""),
                    str(row.get("darkstore_name") or ""),
                    str(row.get("problem") or ""),
                    str(row.get("model") or ""),
                ]
            ).lower()
            if selected_status != "Все" and (row.get("status") or "—") != selected_status:
                continue
            if selected_direction != "Все" and (row.get("direction") or "—") != selected_direction:
                continue
            if selected_type != "Все" and (row.get("request_type") or "—") != selected_type:
                continue
            if selected_master != "Все" and latest_assignment_name(row) != selected_master:
                continue
            if search and search.strip().lower() not in haystack:
                continue
            filtered_requests.append(row)

        st.caption(f"Найдено заявок: {len(filtered_requests)}")
        if not filtered_requests:
            render_empty("По этим фильтрам заявки не найдены.")

        for row in filtered_requests:
            compact_request_card(row)
            with st.expander("Открыть заявку и действия"):
                st.markdown(f"**Дата создания:** {format_dt(row.get('created_at'))}")
                st.markdown(f"**Назначена на:** {latest_assignment_name(row)}")
                st.markdown(f"**Даркстор:** {row.get('darkstore_name') or '—'}")
                st.markdown(f"**Направление:** {row.get('darkstore_direction') or row.get('direction') or '—'}")
                st.markdown(f"**Полный адрес:** {row.get('full_address') or '—'}")
                if row.get("bike_id"):
                    bike_repairs = [repair for repair in repairs if repair.get("bike_id") == row.get("bike_id")]
                    if bike_repairs:
                        st.markdown("**История работ по велосипеду**")
                        for repair in bike_repairs[:6]:
                            st.markdown(f"- Repair `#{repair['id']}` · {repair.get('status') or '—'} · {repair.get('type') or '—'}")
                existing_repair = repair_by_incoming.get(row["id"])
                if existing_repair:
                    st.info(f"По заявке уже есть repair_request #{existing_repair['id']}.")

                with st.form(f"assign_form_{row['id']}"):
                    master_label_map = {full_name(master): master["id"] for master in field_masters}
                    selected_master_label = st.selectbox("Назначить выездному мастеру", list(master_label_map.keys())) if master_label_map else None
                    repair_type = st.selectbox("Тип работы", ["выездной ремонт", "ремонт деталей", "вывоз"])
                    assign_comment = st.text_area("Комментарий диспетчера", height=90)
                    left, right = st.columns(2)
                    assign_clicked = left.form_submit_button("Назначить", type="primary", use_container_width=True)
                    switch_clicked = right.form_submit_button("Сменить тип на вывоз", use_container_width=True)

                if assign_clicked:
                    try:
                        if not selected_master_label:
                            raise ValueError("Нет доступных выездных мастеров.")
                        assign_incoming_request(
                            engine,
                            incoming_id=row["id"],
                            assigned_by=current_user["id"],
                            assigned_to=master_label_map[selected_master_label],
                            repair_type=repair_type,
                            comment=assign_comment.strip(),
                        )
                        refresh_all_caches()
                        flash_success(f"Заявка #{row['id']} назначена.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

                if switch_clicked:
                    try:
                        update_incoming_request_type(engine, incoming_id=row["id"], request_type="вывоз")
                        refresh_all_caches()
                        flash_success(f"Заявка #{row['id']} переведена в тип 'вывоз'.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

    else:
        st.markdown('<div class="section-title">Работы выездных</div>', unsafe_allow_html=True)
        work_cols = st.columns(4)
        repair_status_options = ["Все"] + sorted({row.get("status") or "—" for row in field_master_repairs})
        repair_type_options = ["Все"] + sorted({row.get("type") or "—" for row in field_master_repairs})
        repair_master_options = ["Все"] + sorted({latest_assignment_name(row) for row in field_master_repairs})
        repair_direction_options = ["Все"] + sorted({row.get("darkstore_direction") or "—" for row in field_master_repairs})
        selected_repair_status = work_cols[0].selectbox("Статус работ", repair_status_options, key="dispatcher_repair_status")
        selected_repair_type = work_cols[1].selectbox("Тип работ", repair_type_options, key="dispatcher_repair_type")
        selected_repair_master = work_cols[2].selectbox("Выездной мастер", repair_master_options, key="dispatcher_repair_master")
        selected_repair_direction = work_cols[3].selectbox("Направление дарка", repair_direction_options, key="dispatcher_repair_direction")

        filtered_repairs = []
        for row in field_master_repairs:
            if selected_repair_status != "Все" and (row.get("status") or "—") != selected_repair_status:
                continue
            if selected_repair_type != "Все" and (row.get("type") or "—") != selected_repair_type:
                continue
            if selected_repair_master != "Все" and latest_assignment_name(row) != selected_repair_master:
                continue
            if selected_repair_direction != "Все" and (row.get("darkstore_direction") or "—") != selected_repair_direction:
                continue
            filtered_repairs.append(row)

        st.caption(f"Найдено работ: {len(filtered_repairs)}")
        if not filtered_repairs:
            render_empty("По этим фильтрам работы выездных не найдены.")

        for repair in filtered_repairs:
            compact_repair_card(repair)
            with st.expander("Подробности работы"):
                st.markdown(f"**Проблема:** {repair.get('problem') or '—'}")
                st.markdown(f"**Комментарий назначения:** {repair.get('assignment_comment') or '—'}")
                st.markdown(f"**Комментарий ремонта:** {repair.get('comment') or '—'}")
                st.markdown(f"**Оценка клиента:** {repair.get('client_rating') or '—'}")
                used_parts = [row for row in parts_used if row.get("repair_request_id") == repair["id"]]
                if used_parts:
                    st.markdown("**Запчасти**")
                    for part in used_parts:
                        st.markdown(f"- {part.get('spare_name') or part.get('article') or 'Запчасть'} · {part.get('quantity_used') or 0} шт.")
                else:
                    st.caption("По этой работе запчасти пока не списывались.")


def field_master_dashboard(
    current_user: dict,
    repairs: list[dict],
    bikes: list[dict],
    stock: list[dict],
    master_stock: list[dict],
    parts_used: list[dict],
    work_types: list[dict],
    spare_catalog: list[dict],
    engine,
) -> None:
    my_repairs = sort_field_master_repairs([row for row in repairs if row.get("assigned_to") == current_user["id"]])
    active_repairs = sort_field_master_repairs([row for row in my_repairs if row.get("status") in ACTIVE_MASTER_STATUSES])
    completed_repairs = sort_field_master_repairs([row for row in my_repairs if row.get("status") == "завершена"])
    replacement_repairs = [row for row in my_repairs if row.get("status") == "замена вело"]
    waiting_repairs = [row for row in my_repairs if row.get("status") in {"отложена", "ожидает запчасти"}]
    b2b_rent = [bike for bike in bikes if bike.get("location_status") == "В аренде" and str(bike.get("holder_type") or "").upper() == "B2B"]

    route_map: dict[str, list[dict]] = {}
    for repair in active_repairs:
        key = repair.get("darkstore_name") or "Без даркстора"
        route_map.setdefault(key, []).append(repair)

    parts_for_master = []
    for part in parts_used:
        repair = next((row for row in my_repairs if row["id"] == part.get("repair_request_id")), None)
        if repair:
            payload = dict(part)
            payload["darkstore_name"] = repair.get("darkstore_name")
            parts_for_master.append(payload)

    stock_by_darkstore: dict[str, list[dict]] = {}
    my_darkstores = {repair.get("darkstore_name") for repair in active_repairs if repair.get("darkstore_name")}
    for row in stock:
        if row.get("darkstore_name") in my_darkstores:
            stock_by_darkstore.setdefault(row["darkstore_name"], []).append(row)
    my_trunk_stock = [row for row in master_stock if row.get("master_id") == current_user["id"] and int(row.get("quantity") or 0) > 0]

    role_hero(
        "Выездной мастер",
        "Рабочее место для назначенных, отложенных и завершенных заявок с подготовкой маршрута и запчастей.",
        f"Текущий пользователь: {full_name(current_user)}",
        "Здесь мастер видит дашборд по своим заявкам, рабочий маршрут по дарксторам, доступные запчасти и историю выполненных работ.",
    )

    top = st.columns(6)
    stats = [
        ("Новые", len([row for row in my_repairs if row.get("status") == "новая"])),
        ("Назначены", len([row for row in my_repairs if row.get("status") == "назначена"])),
        ("В работе", len([row for row in my_repairs if row.get("status") == "в работе"])),
        ("Ожидают", len(waiting_repairs)),
        ("Завершены", len(completed_repairs)),
        ("На замену", len(replacement_repairs)),
    ]
    for column, (label, value) in zip(top, stats):
        with column:
            metric_card(label, str(value), "Статус по моим заявкам")

    section = section_switcher("field_master_section", ["Дашборд", "Мои заявки", "Маршрут", "Запчасти", "Выполненные"])

    if section == "Дашборд":
        st.markdown('<div class="section-title">Дашборд</div>', unsafe_allow_html=True)
        left, right = st.columns(2)
        with left:
            render_record_card(
                title="Мои заявки по статусам",
                subtitle="Назначенные, в работе, отложенные и завершенные",
                status=f"{len(my_repairs)} всего",
                fields=[(key, value) for key, value in count_by(my_repairs, "status").items()],
            )
            render_record_card(
                title="Маршрут по дарксторам",
                subtitle="Сколько точек и заявок стоит в маршруте",
                status=f"{len(route_map)} дарков",
                fields=[(darkstore_name, len(rows)) for darkstore_name, rows in sorted(route_map.items(), key=lambda item: item[0])[:6]] or [("Нет точек", "0")],
            )
        with right:
            render_record_card(
                title="B2B контур",
                subtitle="Сколько B2B велосипедов сейчас в аренде",
                status=str(len(b2b_rent)),
                fields=[
                    ("Активных B2B", len(b2b_rent)),
                    ("Моих активных заявок", len(active_repairs)),
                    ("Отложенных", len(waiting_repairs)),
                    ("Замен", len(replacement_repairs)),
                ],
            )
            render_record_card(
                title="Запчасти и выполненные работы",
                subtitle="Краткая сводка по расходу и завершенным выездам",
                status=f"{len(parts_for_master)} списаний",
                fields=[
                    ("Завершенных заявок", len(completed_repairs)),
                    ("Списаний запчастей", len(parts_for_master)),
                    ("Точек в маршруте", len(route_map)),
                    ("Шаблонов работ", len(work_types)),
                ],
            )

    elif section == "Мои заявки":
        st.markdown('<div class="section-title">Мои заявки</div>', unsafe_allow_html=True)
        render_pills(count_by(active_repairs, "status"), red_keys=("назначена", "в работе", "отложена", "замена вело"))
        filter_cols = st.columns(3)
        status_filter_options = ["Все", "назначена", "в работе", "отложена", "ожидает запчасти", "замена вело"]
        direction_filter_options = ["Все"] + sorted({row.get("darkstore_direction") or "—" for row in active_repairs})
        darkstore_filter_options = ["Все"] + sorted({row.get("darkstore_name") or "—" for row in active_repairs})
        selected_status = filter_cols[0].selectbox("Статус", status_filter_options, key="field_master_status_filter")
        selected_direction = filter_cols[1].selectbox("Направление", direction_filter_options, key="field_master_direction_filter")
        selected_darkstore = filter_cols[2].selectbox("Даркстор", darkstore_filter_options, key="field_master_darkstore_filter")

        filtered_active_repairs = []
        for repair in active_repairs:
            if selected_status != "Все" and (repair.get("status") or "—") != selected_status:
                continue
            if selected_direction != "Все" and (repair.get("darkstore_direction") or "—") != selected_direction:
                continue
            if selected_darkstore != "Все" and (repair.get("darkstore_name") or "—") != selected_darkstore:
                continue
            filtered_active_repairs.append(repair)

        if not filtered_active_repairs:
            render_empty("Сейчас на вас не назначено активных заявок.")

        for repair in filtered_active_repairs:
            render_record_card(
                title=f"Заявка #{repair.get('incoming_id') or repair['id']}",
                subtitle=f"{repair.get('darkstore_name') or '—'} · {repair.get('darkstore_direction') or '—'} · {format_short_date(repair.get('updated_at'))}",
                status=repair.get("status") or "—",
                fields=[
                    ("Проблема", repair.get("problem") or "—"),
                    ("Гос номер", repair.get("gov_number") or "—"),
                    ("Модель", repair.get("model") or "—"),
                    ("Адрес", repair.get("full_address") or "—"),
                    ("Тех статус", repair.get("tech_status") or "—"),
                    ("Назначение", repair.get("assignment_comment") or "—"),
                ],
            )
            with st.expander("Открыть заявку"):
                st.markdown(f"**Направление:** {repair.get('darkstore_direction') or '—'}")
                st.markdown(f"**Даркстор:** {repair.get('darkstore_name') or '—'}")
                st.markdown(f"**Проблема:** {repair.get('problem') or '—'}")
                st.markdown(f"**Велосипед:** {repair.get('serial_number') or '—'} / {repair.get('gov_number') or '—'}")

                bike_repairs = [row for row in repairs if row.get("bike_id") == repair.get("bike_id")]
                if bike_repairs:
                    st.markdown("**История работ по велосипеду**")
                    for row in bike_repairs[:6]:
                        st.markdown(f"- Repair `#{row['id']}` · {row.get('status') or '—'} · {row.get('type') or '—'}")

                if repair.get("status") == "назначена":
                    if st.button("Взять в работу", key=f"start_repair_{repair['id']}", type="primary", use_container_width=True):
                        try:
                            start_repair(engine, repair_id=repair["id"])
                            refresh_all_caches()
                            flash_success(f"Repair #{repair['id']} переведен в работу.")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

                suggested_catalog = suggested_spare_parts_for_repair(repair, spare_catalog)
                if suggested_catalog:
                    st.markdown("**Что может понадобиться по описанию проблемы**")
                    for item in suggested_catalog:
                        st.markdown(f"- {item.get('name') or 'Запчасть'}")
                    st.caption("Если нужной позиции нет в багажнике, её лучше сначала добавить в окне `Запчасти`.")

                relevant_trunk = [row for row in my_trunk_stock if int(row.get("quantity") or 0) > 0]
                st.markdown("**Выполнение заявки**")
                work_labels = [row.get("name") for row in work_types]
                with st.form(f"repair_execution_form_{repair['id']}"):
                    selected_works = st.multiselect("Какие работы выполнены", work_labels, key=f"works_{repair['id']}")

                    consumed_parts: list[dict] = []
                    if relevant_trunk:
                        st.markdown("**Какие запчасти использовали из багажника**")
                        for part_row in sorted(relevant_trunk, key=lambda item: (item.get("spare_name") or "").lower()):
                            cols = st.columns([7, 2])
                            cols[0].markdown(f"**{part_row.get('spare_name') or 'Запчасть'}**  \nВ багажнике: {int(part_row.get('quantity') or 0)} шт.")
                            qty = cols[1].number_input(
                                "Кол-во",
                                min_value=0,
                                max_value=max(int(part_row.get("quantity") or 0), 0),
                                value=0,
                                step=1,
                                key=f"consume_qty_{repair['id']}_{part_row['id']}",
                                label_visibility="collapsed",
                            )
                            consumed_parts.append({"master_stock_id": part_row["id"], "quantity": int(qty), "spare_name": part_row.get("spare_name") or "Запчасть"})
                    else:
                        st.caption("Багажник пуст. Если нужны детали, сначала добавьте их в окне `Запчасти`.")

                    comment = st.text_area("Комментарий мастера", height=90, key=f"comment_{repair['id']}")
                    selected_action = st.radio(
                        "Что делаем с заявкой",
                        ["Завершить", "Отложить", "Замена вело"],
                        horizontal=True,
                        key=f"repair_action_{repair['id']}",
                    )
                    postpone_reason = ""
                    if selected_action == "Отложить":
                        postpone_reason = st.text_input("Почему отложили", key=f"postpone_reason_{repair['id']}")

                    apply_clicked = st.form_submit_button("Сохранить и применить", use_container_width=True, type="primary")

                if apply_clicked:
                    try:
                        used_any_parts = False
                        for item in consumed_parts:
                            qty = int(item.get("quantity") or 0)
                            if qty <= 0:
                                continue
                            consume_master_stock(
                                engine,
                                master_stock_id=int(item["master_stock_id"]),
                                repair_request_id=repair["id"],
                                quantity=qty,
                            )
                            used_any_parts = True

                        final_comment = comment.strip()
                        if selected_works:
                            works_line = f"Работы: {', '.join(selected_works)}"
                            final_comment = f"{final_comment}\n{works_line}".strip() if final_comment else works_line

                        if selected_action == "Завершить":
                            finish_repair(engine, repair_id=repair["id"], comment=final_comment)
                            flash_success(f"Заявка #{repair.get('incoming_id') or repair['id']} завершена.")
                        elif selected_action == "Отложить":
                            postpone_repair(engine, repair_id=repair["id"], reason=postpone_reason.strip() or "Нехватка запчастей")
                            flash_success(f"Заявка #{repair.get('incoming_id') or repair['id']} отложена.")
                        else:
                            if used_any_parts or final_comment:
                                flash_success("Запчасти и комментарий сохранены. Процесс замены ещё нужно подключить отдельно.")
                            else:
                                st.info("Процесс замены ещё не подключен к записи в БД.")
                                raise StopIteration

                        refresh_all_caches()
                        st.rerun()
                    except StopIteration:
                        pass
                    except Exception as exc:
                        st.error(str(exc))

    elif section == "Маршрут":
        st.markdown('<div class="section-title">Маршрут</div>', unsafe_allow_html=True)
        if not route_map:
            render_empty("Сейчас нет активных точек для маршрута.")
        route_points = []
        for darkstore_name, rows in sorted(route_map.items(), key=lambda item: item[0]):
            sample = rows[0]
            lat = sample.get("darkstore_latitude")
            lon = sample.get("darkstore_longitude")
            if lat is not None and lon is not None:
                route_points.append(
                    {
                        "darkstore_name": darkstore_name,
                        "direction": sample.get("darkstore_direction") or "—",
                        "requests": len(rows),
                        "lat": float(lat),
                        "lon": float(lon),
                    }
                )

        if route_points:
            route_df = pd.DataFrame(
                {
                    "lat": [point["lat"] for point in route_points],
                    "lon": [point["lon"] for point in route_points],
                }
            )
            st.map(route_df.rename(columns={"lon": "lon", "lat": "lat"}), use_container_width=True)
            yandex_link = build_yandex_maps_link(route_points)
            if yandex_link:
                st.markdown(f"[Открыть маршрут в Яндекс Картах]({yandex_link})")
            st.caption("В приложении показываются точки дарксторов, а маршрут можно открыть в Яндекс Картах.")

        for darkstore_name, rows in sorted(route_map.items(), key=lambda item: item[0]):
            render_record_card(
                title=darkstore_name,
                subtitle="Точка в текущем маршруте",
                status=f"{len(rows)} заявок",
                fields=[
                    ("Направление", rows[0].get("darkstore_direction") or "—"),
                    ("Адрес", rows[0].get("full_address") or "—"),
                    ("Назначены", len([row for row in rows if row.get('status') == 'назначена'])),
                    ("В работе", len([row for row in rows if row.get('status') == 'в работе'])),
                    ("Ожидают", len([row for row in rows if row.get('status') in {'отложена', 'ожидает запчасти'}])),
                    ("На замену", len([row for row in rows if row.get('status') == 'замена вело'])),
                ],
            )
            with st.expander("Открыть список заявок этого дарка"):
                for row in rows:
                    st.markdown(f"- Заявка `#{row.get('incoming_id') or row['id']}` · {row.get('gov_number') or '—'} · {row.get('problem') or '—'} · {row.get('status') or '—'}")
                st.caption("Здесь позже можно будет вручную переставлять порядок точек и выгружать маршрут в Яндекс.")

    elif section == "Запчасти":
        st.markdown('<div class="section-title">Запчасти</div>', unsafe_allow_html=True)
        available_stock = [row for row in stock if int(row.get("quantity") or 0) > 0]
        aggregated_stock = aggregate_stock_by_part(available_stock)

        st.markdown("### Багажник мастера")
        st.caption("Что уже переведено со склада мастеру.")
        if my_trunk_stock:
            for row in sorted(my_trunk_stock, key=lambda item: (item.get("spare_name") or "").lower()):
                st.markdown(f"**{row.get('spare_name') or 'Запчасть'}**")
                st.markdown(f"{int(row.get('quantity') or 0)} шт.")
        else:
            render_empty("Пока пусто. После подтверждения набора на день запчасти появятся здесь.")

        st.markdown("### Подтвердить маршрут и собрать детали")
        todays_repairs = [row for row in active_repairs if row.get("status") in {"назначена", "в работе", "отложена"}]
        selected_today_repairs: list[dict] = []
        suggested_take_map: dict[int, dict] = {}
        if todays_repairs:
            route_labels = {
                f"#{row.get('incoming_id') or row['id']} · {row.get('darkstore_name') or '—'} · {row.get('problem') or '—'}": row
                for row in todays_repairs
            }
            selected_route_labels = st.multiselect(
                "Какие заявки подтверждаете на сегодня",
                list(route_labels.keys()),
                default=list(route_labels.keys()),
            )
            selected_today_repairs = [route_labels[label] for label in selected_route_labels]
            if selected_today_repairs:
                st.markdown("**Подтвержденные заявки на сегодня**")
                for repair in selected_today_repairs:
                    st.markdown(
                        f"- **Заявка #{repair.get('incoming_id') or repair['id']}** · {repair.get('darkstore_name') or '—'} · {repair.get('problem') or '—'}"
                    )
                for repair in selected_today_repairs:
                    for part in suggested_spare_parts_for_repair(repair, spare_catalog):
                        catalog_id = int(part.get("id") or 0)
                        matched_stock = next((row for row in aggregated_stock if row.get("spare_part_catalog_id") == catalog_id), None)
                        if not matched_stock:
                            continue
                        item = suggested_take_map.setdefault(
                            catalog_id,
                            {
                                "spare_part_catalog_id": catalog_id,
                                "spare_name": matched_stock.get("spare_name") or part.get("name") or "Запчасть",
                                "available": int(matched_stock.get("quantity") or 0),
                                "default_qty": 0,
                            },
                        )
                        item["default_qty"] = min(item["available"], int(item["default_qty"]) + 1)
        else:
            render_empty("Нет заявок для подтверждения на сегодняшний маршрут.")

        st.markdown("**Что взять со склада**")
        trunk_catalog_ids = {int(row.get("spare_part_catalog_id")) for row in my_trunk_stock if row.get("spare_part_catalog_id") is not None}
        suggested_take_map = {catalog_id: item for catalog_id, item in suggested_take_map.items() if catalog_id not in trunk_catalog_ids}
        if "field_master_extra_pick_row_ids" not in st.session_state:
            st.session_state["field_master_extra_pick_row_ids"] = [0]
        extra_row_ids = list(st.session_state.get("field_master_extra_pick_row_ids", [0]))

        if aggregated_stock:
            suggested_payload: list[dict] = []
            if suggested_take_map:
                st.caption("Система предложила стартовый набор по комментариям куратора. Позиции из багажника сюда не попадают.")
                for catalog_id, item in sorted(suggested_take_map.items(), key=lambda pair: pair[1]["spare_name"].lower()):
                    cols = st.columns([7, 2])
                    cols[0].markdown(f"**{item['spare_name']}**  \nОстаток: {item['available']} шт.")
                    qty = cols[1].number_input(
                        "Кол-во",
                        min_value=0,
                        max_value=max(item["available"], 0),
                        value=min(item["default_qty"], max(item["available"], 0)),
                        step=1,
                        key=f"take_qty_part_{catalog_id}",
                        label_visibility="collapsed",
                    )
                    suggested_payload.append(
                        {
                            "spare_part_catalog_id": catalog_id,
                            "spare_name": item["spare_name"],
                            "quantity": int(qty),
                        }
                    )
            else:
                st.caption("Автоподсказок пока нет. Можно добавить позиции вручную ниже.")

            part_options = {f"{row.get('spare_name') or 'Запчасть'} · остаток {int(row.get('quantity') or 0)}": row for row in aggregated_stock}
            option_labels = list(part_options.keys())
            extra_payload: list[dict] = []
            for row_id in extra_row_ids:
                cols = st.columns([7, 2, 1])
                selected_label = cols[0].selectbox("Запчасть", option_labels, key=f"manual_part_label_{row_id}", label_visibility="collapsed")
                selected_item = part_options[selected_label]
                qty = cols[1].number_input(
                    "Кол-во",
                    min_value=0,
                    max_value=max(int(selected_item.get("quantity") or 0), 0),
                    value=0,
                    step=1,
                    key=f"manual_part_qty_{row_id}",
                    label_visibility="collapsed",
                )
                remove_clicked = cols[2].button("🗑", key=f"remove_pick_row_{row_id}", use_container_width=True)
                if remove_clicked:
                    st.session_state["field_master_extra_pick_row_ids"] = [rid for rid in extra_row_ids if rid != row_id] or [0]
                    st.rerun()
                extra_payload.append(
                    {
                        "spare_part_catalog_id": int(selected_item["spare_part_catalog_id"]),
                        "spare_name": selected_item.get("spare_name") or "Запчасть",
                        "quantity": int(qty),
                    }
                )

            bottom_cols = st.columns([1, 6])
            if bottom_cols[0].button("+", key="field_master_add_pick_row", use_container_width=True):
                next_id = (max(extra_row_ids) + 1) if extra_row_ids else 0
                st.session_state["field_master_extra_pick_row_ids"] = extra_row_ids + [next_id]
                st.rerun()
            take_clicked = bottom_cols[1].button("Подтвердить выбор на сегодня", key="confirm_take_for_today", type="primary", use_container_width=True)

            if take_clicked:
                try:
                    merged_quantities: dict[int, dict] = {}
                    for item in suggested_payload + extra_payload:
                        qty = int(item.get("quantity") or 0)
                        if qty <= 0:
                            continue
                        catalog_id = int(item["spare_part_catalog_id"])
                        bucket = merged_quantities.setdefault(
                            catalog_id,
                            {"spare_name": item.get("spare_name") or "Запчасть", "quantity": 0},
                        )
                        bucket["quantity"] += qty

                    if not merged_quantities:
                        raise ValueError("Укажите хотя бы одну запчасть и количество больше нуля.")

                    for catalog_id, item in merged_quantities.items():
                        transfer_catalog_stock_to_master(
                            engine,
                            master_id=current_user["id"],
                            spare_part_catalog_id=catalog_id,
                            quantity=int(item["quantity"]),
                        )
                    refresh_all_caches()
                    flash_success("Выбранные запчасти переведены в багажник мастера.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        else:
            render_empty("На складе пока нет остатков, которые можно выдать мастеру.")

        st.markdown("### Вернуть на Склад Цеха")
        if my_trunk_stock:
            return_lines = st.selectbox("Сколько строк вернуть", [1, 2, 3, 4, 5], index=0, key="field_master_return_rows")
            with st.form("return_parts_from_trunk_form"):
                return_payload: list[dict] = []
                trunk_rows_sorted = sorted(
                    [row for row in my_trunk_stock if int(row.get("quantity") or 0) > 0],
                    key=lambda item: (item.get("spare_name") or "").lower(),
                )
                trunk_label_map = {
                    f"{row.get('spare_name') or 'Запчасть'} · {int(row.get('quantity') or 0)} шт.": row
                    for row in trunk_rows_sorted
                }
                trunk_labels = list(trunk_label_map.keys())
                for idx in range(int(return_lines)):
                    st.markdown(f"**Строка возврата {idx + 1}**")
                    selected_label = st.selectbox("Запчасть из багажника", trunk_labels, key=f"return_label_{idx}")
                    selected_row = trunk_label_map[selected_label]
                    qty = st.number_input(
                        f"Количество к возврату для строки {idx + 1}",
                        min_value=0,
                        max_value=max(int(selected_row.get('quantity') or 0), 0),
                        value=0,
                        step=1,
                        key=f"return_qty_{idx}",
                    )
                    return_payload.append({"row": selected_row, "quantity": int(qty)})
                return_clicked = st.form_submit_button("Подтвердить возврат на Склад Цеха", use_container_width=True)

            if return_clicked:
                try:
                    valid_rows = [item for item in return_payload if int(item["quantity"]) > 0]
                    if not valid_rows:
                        raise ValueError("Укажите хотя бы одну позицию для возврата.")
                    for item in valid_rows:
                        trunk_row = item["row"]
                        target_stock = next((row for row in stock if row.get("spare_part_catalog_id") == trunk_row.get("spare_part_catalog_id")), None)
                        if not target_stock:
                            raise ValueError(f"Для запчасти {trunk_row.get('spare_name') or 'Запчасть'} не найден складской остаток, куда вернуть.")
                        return_master_stock_to_storage(
                            engine,
                            master_stock_id=trunk_row["id"],
                            stock_id=target_stock["id"],
                            quantity=int(item["quantity"]),
                        )
                    refresh_all_caches()
                    flash_success("Выбранные запчасти возвращены на Склад Цеха.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        else:
            render_empty("В багажнике мастера пока нет запчастей для возврата.")

    else:
        st.markdown('<div class="section-title">Выполненные заявки</div>', unsafe_allow_html=True)
        if not completed_repairs:
            render_empty("Пока нет завершенных заявок.")
        for repair in completed_repairs:
            used_parts = [row for row in parts_used if row.get("repair_request_id") == repair["id"]]
            render_record_card(
                title=f"Repair #{repair['id']}",
                subtitle=f"{repair.get('darkstore_name') or '—'} · {format_dt(repair.get('updated_at'))}",
                status=repair.get("status") or "—",
                fields=[
                    ("Гос номер", repair.get("gov_number") or "—"),
                    ("Модель", repair.get("model") or "—"),
                    ("Комментарий", repair.get("comment") or "—"),
                    ("Оценка", repair.get("client_rating") or "—"),
                    ("Запчасти", ", ".join(f"{row.get('spare_name') or row.get('article')} ({row.get('quantity_used')})" for row in used_parts) or "—"),
                    ("Работ", "См. комментарий"),
                ],
            )


def workshop_master_dashboard(
    current_user: dict,
    bikes: list[dict],
    repairs: list[dict],
    productivity: list[dict],
    stock: list[dict],
    spare_catalog: list[dict],
    parts_used: list[dict],
    work_types: list[dict],
    engine,
) -> None:
    free_bikes = [bike for bike in bikes if bike.get("location_status") == "Свободен"]
    waiting_repair = [bike for bike in bikes if bike.get("tech_status") == "Ожидает ремонта"]
    workshop_stock = aggregate_stock_by_part([row for row in stock if int(row.get("quantity") or 0) > 0])
    my_repairs = [row for row in repairs if row.get("assigned_to") == current_user["id"]]
    my_completed_repairs = [row for row in my_repairs if row.get("status") == "завершена"]
    built_bikes = [row for row in my_completed_repairs if row.get("type") == "сборка велосипеда"]
    repaired_bikes = [row for row in my_completed_repairs if row.get("type") == "внутренний ремонт"]
    repaired_details = [row for row in my_completed_repairs if row.get("type") == "ремонт деталей"]
    bike_by_id = {bike["id"]: bike for bike in bikes}

    role_hero(
        "Мастер цеха",
        "Поиск по парку, внутренние ремонты, сборка новых велосипедов и выработка по сотрудникам.",
        f"Текущий пользователь: {full_name(current_user)}",
        "Здесь собран парк цеха: можно искать велосипеды, править идентификаторы и запускать внутренний ремонт.",
    )

    a, b, c = st.columns(3)
    with a:
        metric_card("Свободных велосипедов", str(len(free_bikes)), "Location status = Свободен")
    with b:
        metric_card("Наш парк", str(len(bikes)), "Все велосипеды в тестовой базе")
    with c:
        metric_card("Ожидают ремонта", str(len(waiting_repair)), "Tech status = Ожидает ремонта")

    extra_a, extra_b, extra_c = st.columns(3)
    with extra_a:
        metric_card("Собрано велосипедов", str(len(built_bikes)), "Завершённые сборки")
    with extra_b:
        metric_card("Отремонтировано велосипедов", str(len(repaired_bikes)), "Внутренний ремонт")
    with extra_c:
        metric_card("Отремонтировано деталей", str(len(repaired_details)), "Аккумуляторы и мотор-колёса")

    section = section_switcher("workshop_section", ["Список велосипедов", "Сборка нового", "Ремонт деталей", "Продуктивность"])

    if section == "Список велосипедов":
        st.markdown('<div class="section-title">Список велосипедов</div>', unsafe_allow_html=True)
        search = st.text_input("Поиск по серийному номеру, гос номеру или IoT", placeholder="Например, VNT-001 или IOT-001")
        filter_cols = st.columns(3)
        location_options = ["Все"] + sorted({bike.get("location_status") or "—" for bike in bikes})
        tech_options = ["Все"] + sorted({bike.get("tech_status") or "—" for bike in bikes})
        darkstore_options = ["Все"] + sorted({bike.get("darkstore_name") or "—" for bike in bikes})
        location_default_index = location_options.index("Свободен") if "Свободен" in location_options else 0
        selected_location = filter_cols[0].selectbox("Статус локации", location_options, index=location_default_index, key="workshop_location_filter")
        selected_tech = filter_cols[1].selectbox("Тех статус", tech_options, key="workshop_tech_filter")
        selected_darkstore = filter_cols[2].selectbox("Даркстор", darkstore_options, key="workshop_darkstore_filter")

        searched = filter_bikes(bikes, search, ("serial_number", "gov_number", "iot_device_id"))
        filtered = []
        for bike in searched:
            if selected_location != "Все" and (bike.get("location_status") or "—") != selected_location:
                continue
            if selected_tech != "Все" and (bike.get("tech_status") or "—") != selected_tech:
                continue
            if selected_darkstore != "Все" and (bike.get("darkstore_name") or "—") != selected_darkstore:
                continue
            filtered.append(bike)

        st.caption(f"Найдено велосипедов: {len(filtered)}")
        if not filtered:
            render_empty("Велосипеды не найдены.")

        active_workshop_bike_id = st.session_state.get("workshop_active_bike_id")
        active_workshop_bike = bike_by_id.get(active_workshop_bike_id) if active_workshop_bike_id else None
        if active_workshop_bike:
            st.markdown("### Ремонт велосипеда")
            render_record_card(
                title=active_workshop_bike.get("gov_number") or active_workshop_bike.get("serial_number") or f"Bike #{active_workshop_bike['id']}",
                subtitle=f"{active_workshop_bike.get('model') or '—'} · {active_workshop_bike.get('darkstore_name') or 'без даркстора'}",
                status=active_workshop_bike.get("tech_status") or "—",
                fields=[
                    ("Серийный номер", active_workshop_bike.get("serial_number") or "—"),
                    ("IoT", active_workshop_bike.get("iot_device_id") or "—"),
                    ("Локация", active_workshop_bike.get("location_status") or "—"),
                    ("Тех статус", active_workshop_bike.get("tech_status") or "—"),
                ],
            )
            with st.form(f"workshop_repair_form_{active_workshop_bike['id']}"):
                selected_works = st.multiselect(
                    "Какие работы выполнены",
                    [row.get("name") for row in work_types],
                    key=f"workshop_works_{active_workshop_bike['id']}",
                )
                selected_parts = st.multiselect(
                    "Какие детали использовали",
                    [f"{row.get('spare_name') or 'Запчасть'} · остаток {int(row.get('quantity') or 0)}" for row in workshop_stock],
                    key=f"workshop_parts_{active_workshop_bike['id']}",
                )
                selected_part_map = {
                    f"{row.get('spare_name') or 'Запчасть'} · остаток {int(row.get('quantity') or 0)}": row
                    for row in workshop_stock
                }
                consumed_stock_rows: list[dict] = []
                for label in selected_parts:
                    stock_row = selected_part_map[label]
                    qty = st.number_input(
                        f"Количество · {stock_row.get('spare_name') or 'Запчасть'}",
                        min_value=0,
                        max_value=max(int(stock_row.get("quantity") or 0), 0),
                        value=0,
                        step=1,
                        key=f"workshop_part_qty_{active_workshop_bike['id']}_{stock_row['spare_part_catalog_id']}",
                    )
                    consumed_stock_rows.append(
                        {
                            "spare_part_catalog_id": int(stock_row["spare_part_catalog_id"]),
                            "quantity": int(qty),
                            "spare_name": stock_row.get("spare_name") or "Запчасть",
                        }
                    )

                comment = st.text_area("Комментарий по ремонту", height=90, key=f"workshop_comment_{active_workshop_bike['id']}")
                selected_action = st.radio(
                    "Что делаем",
                    ["Взять / сохранить в ремонте", "Завершить ремонт", "Отложить"],
                    horizontal=True,
                    key=f"workshop_action_{active_workshop_bike['id']}",
                )
                postpone_reason = ""
                if selected_action == "Отложить":
                    postpone_reason = st.text_input("Почему отложили", key=f"workshop_postpone_reason_{active_workshop_bike['id']}")
                apply_cols = st.columns(2)
                close_editor = apply_cols[0].form_submit_button("Закрыть окно", use_container_width=True)
                apply_clicked = apply_cols[1].form_submit_button("Применить", type="primary", use_container_width=True)

            if close_editor:
                st.session_state.pop("workshop_active_bike_id", None)
                st.rerun()

            if apply_clicked:
                try:
                    repair_id = ensure_workshop_repair(engine, bike_id=active_workshop_bike["id"], master_id=current_user["id"])
                    for part in consumed_stock_rows:
                        qty = int(part.get("quantity") or 0)
                        if qty <= 0:
                            continue
                        consume_storage_stock(
                            engine,
                            spare_part_catalog_id=int(part["spare_part_catalog_id"]),
                            repair_request_id=repair_id,
                            quantity=qty,
                        )

                    final_comment = comment.strip()
                    if selected_works:
                        works_line = f"Работы: {', '.join(selected_works)}"
                        final_comment = f"{final_comment}\n{works_line}".strip() if final_comment else works_line

                    if selected_action == "Завершить ремонт":
                        finish_repair(engine, repair_id=repair_id, comment=final_comment)
                        flash_success(f"Велосипед #{active_workshop_bike['id']} завершён по ремонту.")
                        st.session_state.pop("workshop_active_bike_id", None)
                    elif selected_action == "Отложить":
                        postpone_repair(engine, repair_id=repair_id, reason=postpone_reason.strip() or "Ожидание детали")
                        flash_success(f"Велосипед #{active_workshop_bike['id']} отложен по ремонту.")
                    else:
                        if final_comment:
                            with engine.begin() as conn:
                                conn.execute(
                                    text(
                                        """
                                        UPDATE repair_request
                                        SET comment = :comment,
                                            status = 'в работе',
                                            updated_at = :updated_at
                                        WHERE id = :repair_id
                                        """
                                    ),
                                    {"comment": final_comment, "updated_at": datetime.now(), "repair_id": repair_id},
                                )
                        flash_success(f"Велосипед #{active_workshop_bike['id']} взят в ремонт.")

                    refresh_all_caches()
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

        for bike in filtered[:30]:
            render_record_card(
                title=bike.get("gov_number") or bike.get("serial_number") or f"Bike #{bike['id']}",
                subtitle=f"{bike.get('model') or '—'} · {bike.get('darkstore_name') or 'без даркстора'}",
                status=bike.get("tech_status") or "—",
                fields=[
                    ("Серийный номер", bike.get("serial_number") or "—"),
                    ("IoT", bike.get("iot_device_id") or "—"),
                    ("Локация", bike.get("location_status") or "—"),
                    ("Тех статус", bike.get("tech_status") or "—"),
                    ("Дней в аренде", bike.get("days_in_rent") or 0),
                    ("Даркстор", bike.get("darkstore_name") or "—"),
                ],
            )
            with st.expander("Работа с велосипедом"):
                bike_repairs = [repair for repair in repairs if repair.get("bike_id") == bike.get("id")]
                if bike_repairs:
                    st.markdown("**История работ**")
                    for row in bike_repairs[:6]:
                        st.markdown(f"- Repair `#{row['id']}` · {row.get('status') or '—'} · {row.get('type') or '—'}")
                else:
                    render_empty("История работ пока пустая.")

                with st.form(f"workshop_edit_{bike['id']}"):
                    serial_number = st.text_input("Серийный номер", value=bike.get("serial_number") or "")
                    gov_number = st.text_input("Гос номер", value=bike.get("gov_number") or "")
                    iot_device_id = st.text_input("IoT", value=bike.get("iot_device_id") or "")
                    tech_status = st.selectbox(
                        "Тех статус",
                        ["Исправен", "Ожидает ремонта", "Ожидает запчасти", "В ремонте", "Ожидает выездного ремонта"],
                        index=["Исправен", "Ожидает ремонта", "Ожидает запчасти", "В ремонте", "Ожидает выездного ремонта"].index(
                            bike.get("tech_status") if bike.get("tech_status") in {"Исправен", "Ожидает ремонта", "Ожидает запчасти", "В ремонте", "Ожидает выездного ремонта"} else "Исправен"
                        ),
                    )
                    save_clicked = st.form_submit_button("Сохранить данные", use_container_width=True)
                if save_clicked:
                    try:
                        update_bike_identity(
                            engine,
                            serial_number=serial_number.strip(),
                            bike_id=bike["id"],
                            gov_number=gov_number.strip(),
                            iot_device_id=iot_device_id.strip(),
                            tech_status=tech_status,
                        )
                        refresh_all_caches()
                        flash_success(f"Данные велосипеда #{bike['id']} обновлены.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
                if st.button("Взять в работу", key=f"open_workshop_repair_{bike['id']}", use_container_width=True):
                    st.session_state["workshop_active_bike_id"] = bike["id"]
                    st.rerun()

    elif section == "Сборка нового":
        st.markdown('<div class="section-title">Сборка нового велосипеда</div>', unsafe_allow_html=True)
        with st.form("new_bike_form", clear_on_submit=True):
            serial_number = st.text_input("Серийный номер")
            gov_number = st.text_input("Гос номер")
            model = st.text_input("Модель")
            iot_device_id = st.text_input("IoT")
            submitted = st.form_submit_button("Добавить велосипед в bike", type="primary", use_container_width=True)
        if submitted:
            try:
                if not serial_number.strip() or not model.strip():
                    raise ValueError("Для сборки нового велосипеда нужны хотя бы серийный номер и модель.")
                create_new_bike(
                    engine,
                    master_id=current_user["id"],
                    serial_number=serial_number.strip(),
                    gov_number=gov_number.strip(),
                    model=model.strip(),
                    iot_device_id=iot_device_id.strip(),
                )
                refresh_all_caches()
                flash_success("Новый велосипед добавлен.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    elif section == "Ремонт деталей":
        st.markdown('<div class="section-title">Ремонт деталей</div>', unsafe_allow_html=True)
        with st.form("detail_repair_form"):
            detail_type = st.radio("Что ремонтируем", ["Аккумулятор", "Мотор-колесо"], horizontal=True)
            serial_or_label = st.text_input("Идентификатор / номер детали")
            diagnosis = st.text_area("Диагностика / комментарий", height=100)
            consumables = st.multiselect(
                "Какие расходники использовали",
                [f"{row.get('spare_name') or 'Запчасть'} · остаток {int(row.get('quantity') or 0)}" for row in workshop_stock],
            )
            selected_consumables_map = {
                f"{row.get('spare_name') or 'Запчасть'} · остаток {int(row.get('quantity') or 0)}": row
                for row in workshop_stock
            }
            consumable_rows: list[dict] = []
            for label in consumables:
                stock_row = selected_consumables_map[label]
                qty = st.number_input(
                    f"Количество · {stock_row.get('spare_name') or 'Запчасть'}",
                    min_value=0,
                    max_value=max(int(stock_row.get("quantity") or 0), 0),
                    value=0,
                    step=1,
                    key=f"detail_consumable_qty_{stock_row['spare_part_catalog_id']}",
                )
                consumable_rows.append(
                    {
                        "spare_part_catalog_id": int(stock_row["spare_part_catalog_id"]),
                        "quantity": int(qty),
                    }
                )
            submitted = st.form_submit_button("Сохранить ремонт детали", use_container_width=True)
        if submitted:
            try:
                create_detail_repair_record(
                    engine,
                    master_id=current_user["id"],
                    detail_type=detail_type,
                    identifier=serial_or_label.strip(),
                    diagnosis=diagnosis.strip(),
                    consumables=consumable_rows,
                )
                refresh_all_caches()
                flash_success(f"Ремонт детали '{detail_type}' сохранён.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    else:
        st.markdown('<div class="section-title">Продуктивность</div>', unsafe_allow_html=True)
        me = next((row for row in productivity if row.get("id") == current_user["id"]), None)
        if not me:
            render_empty("Данных по продуктивности пока нет.")
        else:
            metric_cols = st.columns(3)
            with metric_cols[0]:
                metric_card("Среднее работ в смену", f"{float(me.get('avg_repairs_per_day') or 0):.1f}", "По завершённым работам")
            with metric_cols[1]:
                metric_card("Смен с выработкой", str(me.get("shift_days") or 0), "Дней с завершёнными работами")
            with metric_cols[2]:
                metric_card("Всего завершённых работ", str(me.get("total_repairs") or 0), "Накопительно")

            completed_by_month: dict[str, int] = {}
            recent_repairs = []
            for repair in sorted(my_completed_repairs, key=lambda row: row.get("updated_at") or datetime.min, reverse=True):
                dt = repair.get("updated_at")
                month_key = dt.strftime("%m.%Y") if isinstance(dt, datetime) else str(dt)[:7]
                completed_by_month[month_key] = completed_by_month.get(month_key, 0) + 1
                recent_repairs.append(repair)

            left, right = st.columns(2)
            with left:
                render_record_card(
                    title=full_name(current_user),
                    subtitle="Персональная аналитика мастера цеха",
                    status=f"{float(me.get('avg_repairs_per_day') or 0):.1f} / смену",
                    fields=[
                        ("Среднее работ в смену", f"{float(me.get('avg_repairs_per_day') or 0):.1f}"),
                        ("Смен", me.get("shift_days") or 0),
                        ("Всего завершено", me.get("total_repairs") or 0),
                    ],
                )
                render_record_card(
                    title="Выработка по месяцам",
                    subtitle="Сколько завершённых работ было по прошлым месяцам",
                    status=f"{len(completed_by_month)} мес.",
                    fields=[(month, count) for month, count in sorted(completed_by_month.items(), reverse=True)[:8]] or [("Нет данных", "0")],
                )
                render_record_card(
                    title="Структура работ",
                    subtitle="Что именно делал мастер цеха",
                    status=f"{len(my_completed_repairs)} всего",
                    fields=[
                        ("Сборка велосипедов", len(built_bikes)),
                        ("Ремонт велосипедов", len(repaired_bikes)),
                        ("Ремонт деталей", len(repaired_details)),
                    ],
                )
            with right:
                st.markdown("**Последние работы**")
                if recent_repairs:
                    for repair in recent_repairs[:10]:
                        used_parts = [row for row in parts_used if row.get("repair_request_id") == repair["id"]]
                        parts_line = ", ".join(f"{row.get('spare_name') or row.get('article')} ({row.get('quantity_used')})" for row in used_parts) or "без деталей"
                        st.markdown(
                            f"- {format_dt(repair.get('updated_at'))} · {repair.get('gov_number') or repair.get('serial_number') or '—'} · "
                            f"{repair.get('comment') or repair.get('type') or 'Работа'} · {parts_line}"
                        )
                else:
                    render_empty("У этого мастера пока нет завершённых работ.")


def warehouse_dashboard(
    bikes: list[dict],
    stock: list[dict],
    spare_catalog: list[dict],
    darkstores: list[dict],
    clients: list[dict],
    companies: list[dict],
    rentals: list[dict],
    master_stock: list[dict],
    engine,
) -> None:
    role_hero(
        "Склад",
        "Выдача и возврат аренды, складские остатки и контроль багажников мастеров.",
        "Складской контур",
        "Здесь склад работает с арендой велосипедов, остатками запчастей и движением деталей между складом и мастерами.",
    )

    def bike_label(row: dict) -> str:
        gov = row.get("gov_number") or "Без госномера"
        serial = row.get("serial_number") or f"Bike #{row['id']}"
        model = row.get("model") or "Без модели"
        return f"{gov} · {serial} · {model}"

    def client_label(row: dict) -> str:
        name = row.get("name") or f"Клиент #{row['id']}"
        phone = row.get("phone") or "без телефона"
        return f"{name} · {phone}"

    def company_label(row: dict) -> str:
        name = row.get("name") or f"Компания #{row['id']}"
        company_type = row.get("type") or "B2B"
        return f"{name} · {company_type}"

    def darkstore_label_local(row: dict) -> str:
        name = row.get("name") or f"Даркстор #{row['id']}"
        direction = row.get("direction") or "без направления"
        return f"{name} · {direction}"

    def parse_planned_return(raw_value: str):
        raw_value = (raw_value or "").strip()
        if not raw_value:
            return None
        for fmt in ("%d/%m/%Y", "%d.%m.%Y"):
            try:
                return datetime.strptime(raw_value, fmt)
            except ValueError:
                continue
        raise ValueError("Плановую дату возврата вводите в формате дд/мм/гггг.")

    def rental_days(row: dict) -> int:
        start_dt = row.get("start_dt")
        end_dt = row.get("end_dt") if row.get("status") != "активна" else datetime.now()
        if not start_dt:
            return int(row.get("days_count") or 0)
        if isinstance(start_dt, str):
            try:
                start_dt = datetime.fromisoformat(start_dt)
            except ValueError:
                return int(row.get("days_count") or 0)
        if isinstance(end_dt, str):
            try:
                end_dt = datetime.fromisoformat(end_dt)
            except ValueError:
                end_dt = datetime.now()
        return max((end_dt.date() - start_dt.date()).days, 0)

    free_serviceable_bikes = [
        row for row in bikes
        if row.get("location_status") == "Свободен" and row.get("tech_status") == "Исправен"
    ]
    active_rentals = [row for row in rentals if row.get("status") == "активна"]
    private_clients = [row for row in clients if (row.get("type") or "").strip().lower() == "физлицо"]

    top_cols = st.columns(3)
    with top_cols[0]:
        metric_card("Готово к выдаче", str(len(free_serviceable_bikes)), "Свободные и исправные велосипеды")
    with top_cols[1]:
        metric_card("Активные аренды", str(len(active_rentals)), "Текущие выдачи")
    with top_cols[2]:
        metric_card("B2B компаний", str(len(companies)), "Компании для корпоративной аренды")

    section = section_switcher("warehouse_section", ["Велосипеды", "Аренда", "Запчасти"])

    if section == "Велосипеды":
        st.markdown('<div class="section-title">Карточки велосипедов</div>', unsafe_allow_html=True)
        search = st.text_input("Поиск по серийному номеру или госномеру")
        location_filter = st.selectbox(
            "Статус локации",
            ["Все"] + sorted({row.get("location_status") or "—" for row in bikes}),
        )
        tech_filter = st.selectbox(
            "Техстатус",
            ["Все"] + sorted({row.get("tech_status") or "—" for row in bikes}),
        )
        filtered = filter_bikes(bikes, search, ("serial_number", "gov_number", "iot_device_id"))
        if location_filter != "Все":
            filtered = [row for row in filtered if (row.get("location_status") or "—") == location_filter]
        if tech_filter != "Все":
            filtered = [row for row in filtered if (row.get("tech_status") or "—") == tech_filter]
        if not filtered:
            render_empty("Велосипеды не найдены.")
        else:
            st.caption(f"Найдено велосипедов: {len(filtered)}")
            for bike in filtered[:50]:
                render_record_card(
                    title=bike.get("gov_number") or bike.get("serial_number") or f"Bike #{bike['id']}",
                    subtitle=bike.get("model") or "Без модели",
                    status=bike.get("location_status") or "—",
                    fields=[
                        ("Серийный номер", bike.get("serial_number") or "—"),
                        ("IoT", bike.get("iot_device_id") or "—"),
                        ("Техстатус", bike.get("tech_status") or "—"),
                        ("Даркстор", bike.get("darkstore_name") or "—"),
                        ("Дней в аренде", bike.get("days_in_rent") or 0),
                    ],
                )

    elif section == "Аренда":
        st.markdown('<div class="section-title">Выдача в аренду</div>', unsafe_allow_html=True)
        rental_section = section_switcher("warehouse_rental_section", ["Частное лицо", "B2B", "Активные аренды"])

        if rental_section == "Частное лицо":
            with st.expander("Создать нового клиента"):
                with st.form("warehouse_create_private_client_form", clear_on_submit=True):
                    new_client_name = st.text_input("ФИО")
                    new_client_phone = st.text_input("Телефон")
                    passport_number = st.text_input("Паспорт: номер")
                    passport_issued_by = st.text_input("Паспорт: кем выдан")
                    passport_issue_date = st.text_input("Паспорт: дата выдачи")
                    passport_note = st.text_area("Комментарий", height=80)
                    submit_new_client = st.form_submit_button("Создать клиента", use_container_width=True)
                if submit_new_client:
                    try:
                        if not new_client_name.strip():
                            raise ValueError("Укажите ФИО клиента.")
                        passport_payload = {
                            "number": passport_number.strip(),
                            "issued_by": passport_issued_by.strip(),
                            "issue_date": passport_issue_date.strip(),
                            "comment": passport_note.strip(),
                        }
                        create_private_client(
                            engine,
                            name=new_client_name.strip(),
                            phone=new_client_phone.strip(),
                            passport_data=passport_payload,
                        )
                        refresh_all_caches()
                        flash_success("Новый клиент создан.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

            if not free_serviceable_bikes:
                render_empty("Нет свободных и исправных велосипедов для выдачи.")
            elif not private_clients:
                render_empty("Сначала создайте хотя бы одного клиента.")
            else:
                bike_map = {bike_label(row): row for row in free_serviceable_bikes}
                client_map = {client_label(row): row for row in private_clients}
                default_return_date = date.today()
                bike_choice = st.selectbox("Велосипед", list(bike_map.keys()), key="warehouse_b2c_bike")
                client_choice = st.selectbox("Клиент", list(client_map.keys()), key="warehouse_b2c_client")
                planned_return_date = st.date_input(
                    "Плановая дата возврата",
                    value=default_return_date,
                    format="DD/MM/YYYY",
                    key="warehouse_b2c_return_date",
                )
                rental_period_days = max((planned_return_date - date.today()).days, 0)
                st.caption(
                    f"Период аренды: с {date.today().strftime('%d/%m/%Y')} "
                    f"по {planned_return_date.strftime('%d/%m/%Y')} · {rental_period_days} дн."
                )
                tariff = st.text_input("Тариф", key="warehouse_b2c_tariff")
                submit_b2c = st.button("Выдать в аренду", type="primary", use_container_width=True, key="warehouse_b2c_submit")
                st.caption("Для частного клиента даркстор не выбирается. Тариф пока показывается только в интерфейсе.")
                if submit_b2c:
                    try:
                        planned_return_dt = datetime.combine(planned_return_date, datetime.min.time())
                        bike = bike_map[bike_choice]
                        client = client_map[client_choice]
                        issue_b2c_rental(
                            engine,
                            bike_id=int(bike["id"]),
                            client_id=int(client["id"]),
                            planned_return_dt=planned_return_dt,
                        )
                        refresh_all_caches()
                        message = f"Велосипед {bike.get('gov_number') or bike.get('serial_number')} выдан клиенту {client.get('name')}."
                        if planned_return_dt:
                            message += f" Плановый возврат: {planned_return_dt.strftime('%d.%m.%Y')}."
                            message += f" Срок аренды: {rental_period_days} дн."
                        if tariff.strip():
                            message += f" Тариф: {tariff.strip()}."
                        flash_success(message)
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

        elif rental_section == "B2B":
            with st.expander("Создать новую компанию"):
                with st.form("warehouse_create_company_form", clear_on_submit=True):
                    company_name = st.text_input("Название компании")
                    company_type = st.text_input("Тип компании", value="B2B")
                    submit_company = st.form_submit_button("Создать компанию", use_container_width=True)
                if submit_company:
                    try:
                        if not company_name.strip():
                            raise ValueError("Укажите название компании.")
                        create_company(engine, name=company_name.strip(), company_type=company_type.strip() or "B2B")
                        refresh_all_caches()
                        flash_success("Новая компания создана.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

            if not companies:
                render_empty("Сначала создайте хотя бы одну компанию.")
            elif not free_serviceable_bikes:
                render_empty("Нет свободных и исправных велосипедов для выдачи.")
            else:
                company_map = {company_label(row): row for row in companies}
                selected_company_label = st.selectbox("Компания", list(company_map.keys()), key="warehouse_b2b_company_select")
                selected_company = company_map[selected_company_label]
                company_darkstores = [
                    row
                    for row in darkstores
                    if int(row.get("company_id") or 0) == int(selected_company.get("id") or 0)
                ]
                if not company_darkstores:
                    st.warning("У этой компании пока нет дарксторов. Сначала добавьте даркстор компании.")
                else:
                    darkstore_map_local = {darkstore_label_local(row): row for row in company_darkstores}
                    bike_map = {bike_label(row): row for row in free_serviceable_bikes}
                    with st.form("warehouse_issue_b2b_form"):
                        darkstore_choice = st.selectbox("Даркстор компании", list(darkstore_map_local.keys()))
                        bike_choices = st.multiselect("Велосипеды", list(bike_map.keys()))
                        submit_b2b = st.form_submit_button("Выдать компании", type="primary", use_container_width=True)
                    if submit_b2b:
                        try:
                            if not bike_choices:
                                raise ValueError("Выберите хотя бы один велосипед.")
                            darkstore_row = darkstore_map_local[darkstore_choice]
                            bike_ids = [int(bike_map[label]["id"]) for label in bike_choices]
                            inserted = issue_b2b_rental(
                                engine,
                                bike_ids=bike_ids,
                                company_id=int(selected_company["id"]),
                                darkstore_id=int(darkstore_row["id"]),
                            )
                            refresh_all_caches()
                            flash_success(
                                f"Выдано велосипедов: {inserted}. Компания: {selected_company.get('name')}. Даркстор: {darkstore_row.get('name')}."
                            )
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

        else:
            filter_cols = st.columns(3)
            search_value = filter_cols[0].text_input("Поиск", placeholder="Клиент, компания, госномер, серийный номер")
            rent_type = filter_cols[1].selectbox("Тип аренды", ["Все", "B2C", "B2B"])
            darkstore_options = ["Все"] + sorted({row.get("darkstore_name") or "Без даркстора" for row in active_rentals})
            darkstore_filter = filter_cols[2].selectbox("Даркстор", darkstore_options)

            filtered_rentals = active_rentals[:]
            if search_value.strip():
                needle = search_value.strip().lower()
                filtered_rentals = [
                    row for row in filtered_rentals
                    if needle in " ".join([
                        str(row.get("client_name") or ""),
                        str(row.get("company_name") or ""),
                        str(row.get("gov_number") or ""),
                        str(row.get("serial_number") or ""),
                    ]).lower()
                ]
            if rent_type == "B2C":
                filtered_rentals = [row for row in filtered_rentals if row.get("client_id") is not None]
            elif rent_type == "B2B":
                filtered_rentals = [row for row in filtered_rentals if row.get("company_id") is not None]
            if darkstore_filter != "Все":
                filtered_rentals = [
                    row for row in filtered_rentals
                    if (row.get("darkstore_name") or "Без даркстора") == darkstore_filter
                ]

            if not filtered_rentals:
                render_empty("Аренды по выбранным фильтрам не найдены.")
            else:
                for row in filtered_rentals[:80]:
                    tenant_name = row.get("client_name") or row.get("company_name") or "—"
                    tenant_type = "B2C" if row.get("client_id") is not None else "B2B"
                    planned_return = format_short_date(row.get("end_dt")) if row.get("end_dt") else "—"
                    render_record_card(
                        title=row.get("gov_number") or row.get("serial_number") or f"Аренда #{row['id']}",
                        subtitle=f"{tenant_name} · {tenant_type}",
                        status=row.get("status") or "—",
                        fields=[
                            ("Велосипед", row.get("serial_number") or "—"),
                            ("Начало аренды", format_dt(row.get("start_dt"))),
                            ("Плановый возврат", planned_return),
                            ("Дней в аренде", rental_days(row)),
                            ("Даркстор", row.get("darkstore_name") or "—"),
                        ],
                    )
                    if row.get("status") == "активна":
                        action_cols = st.columns([1, 1, 3])
                        if action_cols[0].button("Завершить аренду", key=f"finish_rental_{row['id']}", use_container_width=True, type="primary"):
                            try:
                                finish_rental(engine, rental_id=int(row["id"]))
                                refresh_all_caches()
                                flash_success("Аренда завершена.")
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))
                        if action_cols[1].button("Сообщить о краже", key=f"theft_rental_{row['id']}", use_container_width=True):
                            try:
                                report_rental_theft(engine, rental_id=int(row["id"]))
                                refresh_all_caches()
                                flash_success("По аренде зафиксирована кража велосипеда.")
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))

    else:
        st.markdown('<div class="section-title">Запчасти</div>', unsafe_allow_html=True)
        catalog_map = {
            f"{row.get('name') or row.get('article') or 'Запчасть'} · {row.get('article') or 'без артикула'}": row
            for row in spare_catalog
        }
        darkstore_map = {darkstore_label_local(row): row for row in darkstores}

        stock_search = st.text_input("Поиск запчасти", key="warehouse_stock_search")
        filtered_stock = stock[:]
        if stock_search.strip():
            needle = stock_search.strip().lower()
            filtered_stock = [
                row for row in filtered_stock
                if needle in " ".join([
                    str(row.get("spare_name") or ""),
                    str(row.get("article") or ""),
                    str(row.get("darkstore_name") or ""),
                ]).lower()
            ]

        if filtered_stock:
            for row in filtered_stock[:80]:
                render_record_card(
                    title=row.get("spare_name") or row.get("article") or "Запчасть",
                    subtitle=row.get("darkstore_name") or "Без даркстора",
                    status=f"{int(row.get('quantity') or 0)} шт.",
                    fields=[
                        ("Артикул", row.get("article") or "—"),
                        ("Остаток", int(row.get("quantity") or 0)),
                    ],
                )
        else:
            render_empty("Остатков по выбранному поиску нет.")

        with st.form("warehouse_stock_adjust_form"):
            mode = st.selectbox("Операция", ["Приход", "Списание"])
            catalog_choice = st.selectbox("Номенклатура", list(catalog_map.keys()) if catalog_map else ["Нет запчастей"])
            darkstore_choice = st.selectbox("Склад / даркстор", list(darkstore_map.keys()) if darkstore_map else ["Нет дарксторов"])
            quantity = st.number_input("Количество", min_value=1, step=1)
            submit_stock = st.form_submit_button("Провести операцию", use_container_width=True)
        if submit_stock and catalog_map and darkstore_map:
            try:
                catalog_row = catalog_map[catalog_choice]
                darkstore_row = darkstore_map[darkstore_choice]
                existing = next(
                    (
                        row for row in stock
                        if row.get("spare_part_catalog_id") == catalog_row["id"] and row.get("darkstore_id") == darkstore_row["id"]
                    ),
                    None,
                )
                delta = quantity if mode == "Приход" else -quantity
                adjust_stock(
                    engine,
                    stock_id=existing.get("id") if existing else None,
                    spare_part_catalog_id=int(catalog_row["id"]),
                    darkstore_id=int(darkstore_row["id"]),
                    delta=int(delta),
                )
                refresh_all_caches()
                flash_success("Остаток запчастей обновлён.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        st.markdown("### Багажники мастеров")
        nonzero_master_stock = [row for row in master_stock if int(row.get("quantity") or 0) > 0]
        if not nonzero_master_stock:
            render_empty("Сейчас в багажниках мастеров нет запчастей.")
        else:
            grouped: dict[str, list[dict]] = {}
            for row in nonzero_master_stock:
                grouped.setdefault(full_name(row), []).append(row)
            for master_name, rows in sorted(grouped.items(), key=lambda item: item[0]):
                render_record_card(
                    title=master_name,
                    subtitle="Что сейчас находится у мастера",
                    status=f"{sum(int(row.get('quantity') or 0) for row in rows)} шт.",
                    fields=[
                        (row.get("spare_name") or "Запчасть", f"{int(row.get('quantity') or 0)} шт.")
                        for row in sorted(rows, key=lambda item: (item.get("spare_name") or "").lower())[:12]
                    ],
                )

        negative_stock = [row for row in stock if int(row.get("quantity") or 0) < 0]
        if negative_stock:
            st.error("Есть отрицательные остатки на складе. Значит списание со стока прошло некорректно.")
        else:
            st.success("Отрицательных остатков на складе нет. Текущие списания со склада выглядят корректно.")


def render_role_screen(role_key: str, context: dict, data: dict, engine) -> None:
    if role_key == "curator":
        curator_dashboard(context["darkstore"], data["incoming_requests"], data["bikes"], data["bike_logs"], engine)
    elif role_key == "dispatcher":
        dispatcher_dashboard(
            context["employee"],
            data["incoming_requests"],
            data["repairs"],
            data["bikes"],
            data["employees"],
            data["productivity"],
            data["parts_used"],
            engine,
        )
    elif role_key == "field_master":
        field_master_dashboard(
            context["employee"],
            data["repairs"],
            data["bikes"],
            data["stock"],
            data["master_stock"],
            data["parts_used"],
            data["work_types"],
            data["spare_catalog"],
            engine,
        )
    elif role_key == "workshop_master":
        workshop_master_dashboard(
            context["employee"],
            data["bikes"],
            data["repairs"],
            data["productivity"],
            data["stock"],
            data["spare_catalog"],
            data["parts_used"],
            data["work_types"],
            engine,
        )
    else:
        warehouse_dashboard(
            data["bikes"],
            data["stock"],
            data["spare_catalog"],
            data["darkstores"],
            data["clients"],
            data["companies"],
            data["rentals"],
            data["master_stock"],
            engine,
        )


def choose_employee(role_key: str, employees: list[dict]) -> dict | None:
    allowed = set(EMPLOYEE_ROLE_MAP.get(role_key, ()))
    matched = [row for row in employees if row.get("role") in allowed]
    if not matched:
        return None
    options = {full_name(row): row for row in matched}
    selected = st.sidebar.selectbox("Сотрудник", list(options.keys()))
    return options[selected]


def load_all_data(engine) -> dict:
    return {
        "darkstores": load_darkstores(engine),
        "employees": load_employees(engine),
        "clients": load_clients(engine),
        "companies": load_companies(engine),
        "rentals": load_rentals(engine),
        "bikes": load_bikes(engine),
        "incoming_requests": load_incoming_requests(engine),
        "repairs": load_repairs(engine),
        "bike_logs": load_bike_logs(engine),
        "stock": load_spare_stock(engine),
        "master_stock": load_master_spare_stock(engine),
        "spare_catalog": load_spare_catalog(engine),
        "parts_used": load_parts_used(engine),
        "work_types": load_work_types(engine),
        "productivity": load_productivity(engine),
    }


def main() -> None:
    inject_styles()
    render_flash()

    try:
        engine = get_engine()
    except Exception as exc:
        st.error("Не удалось создать подключение к базе данных.")
        st.code(str(exc))
        return

    is_connected, connection_error = check_database_connection(engine)
    if not is_connected:
        st.error("База данных сейчас недоступна.")
        st.info("Соединение с Supabase pooler оборвалось до загрузки данных. Обычно это временно: попробуйте перезапустить страницу через несколько секунд.")
        if connection_error:
            st.code(connection_error)
        return

    try:
        data = load_all_data(engine)
    except Exception as exc:
        st.error("Не удалось загрузить данные из базы.")
        st.code(str(exc))
        return

    st.sidebar.markdown("## Роль")
    role_key = st.sidebar.selectbox(
        "Роль",
        list(ROLE_LABELS.keys()),
        format_func=lambda value: ROLE_LABELS[value],
        label_visibility="collapsed",
    )

    context: dict = {}
    if role_key == "curator":
        darkstore_map = {row.get("name") or str(row["id"]): row for row in data["darkstores"]}
        selected_name = st.sidebar.selectbox("Даркстор", list(darkstore_map.keys()))
        context["darkstore"] = darkstore_map[selected_name]
    else:
        employee = choose_employee(role_key, data["employees"])
        if not employee:
            st.warning("Для этой роли пока нет сотрудников в базе.")
            return
        context["employee"] = employee

    render_role_screen(role_key, context, data, engine)


if __name__ == "__main__":
    main()
