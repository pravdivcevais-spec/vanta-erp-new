"""
ui.py — стили и переиспользуемые UI-компоненты.
"""

import html

import streamlit as st


# ===========================================================================
# СТИЛИ
# ===========================================================================

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

        .stApp { background: var(--bg); color: var(--ink); }
        .block-container { padding-top: 1.25rem; padding-bottom: 2rem; }

        section[data-testid="stSidebar"] { background: #23242d; }
        section[data-testid="stSidebar"] * { color: #ffffff; }
        section[data-testid="stSidebar"] .stSelectbox label,
        section[data-testid="stSidebar"] .stRadio label { color: #ffffff !important; }

        .hero {
            background: #101012; color: #ffffff;
            border-radius: 30px; padding: 30px 36px;
            box-shadow: 0 20px 54px rgba(15,15,16,.18); margin-bottom: 1rem;
        }
        .hero-eyebrow { font-size:.76rem; text-transform:uppercase; letter-spacing:.14em; opacity:.68; }
        .hero-title { font-size:2.3rem; font-weight:850; margin:.35rem 0 .55rem 0; }
        .hero-subtitle { font-size:1rem; line-height:1.55; color:rgba(255,255,255,.84); max-width:920px; }
        .hero-context { margin-top:.9rem; font-size:1.08rem; font-weight:800; color:#ffffff; }
        .hero-note { margin-top:.24rem; color:rgba(255,255,255,.78); font-size:.95rem; }

        .metric-card {
            background: var(--panel); border:1px solid var(--line);
            border-top:4px solid var(--accent); border-radius:24px;
            padding:18px 20px; min-height:120px; box-shadow:var(--shadow); margin-bottom:.3rem;
        }
        .metric-label { color:var(--muted); font-size:.78rem; text-transform:uppercase; letter-spacing:.08em; }
        .metric-value { color:var(--ink); font-size:2.05rem; font-weight:850; line-height:1; margin:.42rem 0 .24rem 0; }
        .metric-note { color:var(--muted); font-size:.93rem; line-height:1.4; }

        .record-card {
            background:#ffffff; border:1px solid rgba(15,15,16,.08); border-radius:26px;
            padding:20px 22px 18px 22px; box-shadow:0 14px 34px rgba(15,15,16,.045); margin:0 0 18px 0;
        }
        .record-top { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; margin-bottom:14px; }
        .record-title { font-size:1.15rem; font-weight:850; color:var(--ink); margin-bottom:.22rem; }
        .record-subtitle { font-size:.93rem; color:var(--muted); line-height:1.45; }
        .record-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px 18px; }
        .record-field { border-top:1px solid var(--line); padding-top:10px; }
        .record-field-label { color:var(--muted); font-size:.76rem; text-transform:uppercase; letter-spacing:.06em; margin-bottom:.3rem; }
        .record-field-value { color:var(--ink); font-size:1rem; font-weight:650; line-height:1.38; }

        .chip {
            display:inline-flex; align-items:center; padding:.38rem .8rem;
            border-radius:999px; font-size:.82rem; font-weight:800;
            white-space:nowrap; border:1px solid transparent;
        }
        .chip-dark { background:#111111; color:#ffffff; }
        .chip-red { background:#d0021b; color:#ffffff; }
        .chip-soft-red { background:rgba(208,2,27,.1); color:#980011; border-color:rgba(208,2,27,.14); }
        .chip-default { background:#efeff1; color:#222228; }

        .pill-row { margin-bottom:.85rem; }
        .pill {
            display:inline-block; padding:.36rem .72rem; border-radius:999px;
            margin-right:.42rem; margin-bottom:.4rem;
            background:#ececef; color:#17171a; font-size:.82rem; font-weight:750;
        }
        .pill.red { background:rgba(208,2,27,.1); color:#980011; }

        .empty {
            border:1px dashed var(--line-strong); border-radius:18px;
            background:#fafafa; padding:18px; color:var(--muted);
        }
        .subtle-note { color:var(--muted); font-size:.92rem; }
        .section-title { font-size:1.95rem; font-weight:850; margin:.45rem 0 .75rem 0; }
        .section-caption { color:var(--muted); margin:-.25rem 0 .85rem 0; }

        div[role="radiogroup"] { gap:10px; }
        div[role="radiogroup"] label {
            background:#ffffff; border:1px solid rgba(15,15,16,.12);
            border-radius:16px; min-height:48px; padding:10px 16px;
            box-shadow:0 4px 10px rgba(15,15,16,.02);
        }
        div[role="radiogroup"] label:has(input:checked) { background:#111111; border-color:#111111; }
        div[role="radiogroup"] label:has(input:checked) p { color:#ffffff !important; }
        div[role="radiogroup"] p { font-weight:800; color:#111111; }

        div[data-testid="stWidgetLabel"] p,
        label[data-testid="stWidgetLabel"] p { color:#111111 !important; font-weight:700 !important; }
        section[data-testid="stSidebar"] div[data-testid="stWidgetLabel"] p,
        section[data-testid="stSidebar"] label[data-testid="stWidgetLabel"] p { color:#ffffff !important; }

        .stTextInput input, .stTextArea textarea {
            background:#1a1b20 !important; color:#ffffff !important; border:1px solid #1a1b20 !important;
        }
        .stTextInput input::placeholder, .stTextArea textarea::placeholder { color:rgba(255,255,255,.66) !important; }

        .stSelectbox [data-baseweb="select"] > div,
        .stMultiSelect [data-baseweb="select"] > div {
            background:#ffffff !important; color:#111111 !important; border-color:rgba(15,15,16,.14) !important;
        }
        section[data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] > div,
        section[data-testid="stSidebar"] .stMultiSelect [data-baseweb="select"] > div {
            background:#2e2f3a !important; color:#ffffff !important; border-color:rgba(255,255,255,.15) !important;
        }
        section[data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] > div *,
        section[data-testid="stSidebar"] .stMultiSelect [data-baseweb="select"] > div * {
            color:#ffffff !important; fill:#ffffff !important;
        }
        section[data-testid="stSidebar"] [data-baseweb="popover"] li,
        section[data-testid="stSidebar"] [data-baseweb="menu"] li {
            background:#2e2f3a !important; color:#ffffff !important;
        }

        .stButton button, .stFormSubmitButton button, .stDownloadButton button,
        button[data-testid^="stBaseButton-"] {
            border-radius:14px !important; border:1px solid rgba(15,15,16,.14) !important;
            background:#ffffff !important; color:#111111 !important;
            font-weight:750 !important; box-shadow:none !important;
        }
        .stButton button[kind="primary"], .stButton button[data-testid="stBaseButton-primary"],
        .stFormSubmitButton button[kind="primary"], .stFormSubmitButton button[data-testid="stBaseButton-primary"] {
            background:#111111 !important; color:#ffffff !important; border-color:#111111 !important;
        }
        .stButton button[kind="primary"]:hover, .stFormSubmitButton button[kind="primary"]:hover {
            background:#1b1c22 !important; color:#ffffff !important; border-color:#1b1c22 !important;
        }
        .stButton button:hover, .stFormSubmitButton button:hover, .stDownloadButton button:hover {
            background:#f2f2f4 !important; color:#111111 !important; border-color:rgba(15,15,16,.22) !important;
        }
        .stButton button p, .stFormSubmitButton button p, .stDownloadButton button p,
        .stButton button span, .stFormSubmitButton button span, .stDownloadButton button span {
            color:inherit !important;
        }
        .stButton button[kind="primary"] p, .stButton button[data-testid="stBaseButton-primary"] p,
        .stFormSubmitButton button[kind="primary"] p { color:#ffffff !important; }

        @media (max-width:960px) { .record-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
        @media (max-width:640px) { .record-grid { grid-template-columns:1fr; } .record-top { flex-direction:column; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ===========================================================================
# FLASH-СООБЩЕНИЯ
# ===========================================================================

def flash_success(message: str) -> None:
    st.session_state["flash_success"] = message


def render_flash() -> None:
    message = st.session_state.pop("flash_success", None)
    if message:
        st.success(message)


# ===========================================================================
# КОМПОНЕНТЫ
# ===========================================================================

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


def role_hero(title: str, subtitle: str, context: str, note: str) -> None:
    st.markdown(
        f"""
        <div class="hero">
            <div class="hero-eyebrow">Vanta ERP · Рабочее место</div>
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


def compact_request_card(row: dict, latest_assignment_name_fn) -> None:
    from utils import format_short_date
    title = f"#{row['id']} · {row.get('device_type') or 'Велосипед'}"
    subtitle = f"{row.get('darkstore_name') or '—'} · {format_short_date(row.get('created_at'))}"
    fields = [
        ("Гос номер", row.get("gov_number") or "—"),
        ("Модель", row.get("model") or "—"),
        ("Проблема", row.get("problem") or "—"),
        ("Мастер", latest_assignment_name_fn(row)),
    ]
    render_record_card(title=title, subtitle=subtitle, status=row.get("status") or "—", fields=fields)


def compact_repair_card(row: dict, latest_assignment_name_fn) -> None:
    title = f"Работа #{row['id']} · {row.get('type') or '—'}"
    subtitle = f"{row.get('darkstore_name') or '—'} · {latest_assignment_name_fn(row)}"
    from utils import format_dt
    fields = [
        ("Гос номер", row.get("gov_number") or "—"),
        ("Проблема", row.get("problem") or "—"),
        ("Запрос", f"#{row.get('incoming_id')}" if row.get("incoming_id") else "Внутренний"),
        ("Обновлено", format_dt(row.get("updated_at"))),
    ]
    render_record_card(title=title, subtitle=subtitle, status=row.get("status") or "—", fields=fields)
