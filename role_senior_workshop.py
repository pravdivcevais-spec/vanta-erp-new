"""
role_senior_workshop.py — кабинет старшего мастера цеха.

Обязанности:
  - Проверяет ремонты со статусом «на проверке»
  - Принимает (→ завершена, велосипед → Исправен) или отправляет на доработку (косяк)
  - Видит статистику косяков по мастерам
"""

import streamlit as st

from db import (
    approve_repair,
    load_repairs,
    load_rework_stats,
    load_reviews_pending,
    refresh_all_caches,
    reject_repair,
)
from ui import flash_success, render_record_card, section_switcher
from utils import full_name


def senior_workshop_dashboard(
    current_user: dict,
    engine,
) -> None:
    st.markdown(
        f"<div class='hero'><h2>Старший мастер цеха</h2>"
        f"<p>{full_name(current_user)}</p></div>",
        unsafe_allow_html=True,
    )

    pending = load_reviews_pending(engine)
    stats   = load_rework_stats(engine)

    badge = f" ({len(pending)})" if pending else ""
    section = section_switcher(
        "senior_workshop_section",
        [f"На проверке{badge}", "Статистика косяков"],
    )

    if section.startswith("На проверке"):
        _section_pending(pending, engine)
    else:
        _section_stats(stats)


# ---------------------------------------------------------------------------
# Ремонты на проверке
# ---------------------------------------------------------------------------

def _section_pending(pending: list[dict], engine) -> None:
    if not pending:
        st.info("Нет ремонтов, ожидающих проверки.")
        return

    st.markdown(f"**{len(pending)} ремонт(ов) ждут проверки**")

    for repair in pending:
        bike_label = (
            repair.get("gov_number")
            or repair.get("serial_number")
            or f"Велосипед #{repair.get('bike_id', '?')}"
        )
        master_name = full_name({
            "first_name": repair.get("master_first_name"),
            "last_name":  repair.get("master_last_name"),
        })
        rework = int(repair.get("rework_count") or 0)
        rework_label = f" · ⚠️ Косяков: {rework}" if rework else ""

        render_record_card(
            title=bike_label,
            subtitle=f"Мастер: {master_name}{rework_label}",
            status="на проверке",
            fields=[
                ("Модель",        repair.get("model") or "—"),
                ("Серийный №",    repair.get("serial_number") or "—"),
                ("Тип ремонта",   repair.get("type") or "—"),
                ("Комментарий",   repair.get("comment") or "—"),
            ],
        )

        with st.expander(f"Принять / На доработку — {bike_label}"):
            col_ok, col_bad = st.columns(2)

            with col_ok:
                accept_comment = st.text_area(
                    "Комментарий при приёмке (необязательно)",
                    key=f"accept_comment_{repair['id']}",
                    placeholder="Всё хорошо, принято",
                )
                if st.button("✅ Принять ремонт", key=f"accept_{repair['id']}", type="primary"):
                    try:
                        approve_repair(engine, repair_id=repair["id"], comment=accept_comment)
                        flash_success(f"Ремонт велосипеда {bike_label} принят. Велосипед → Исправен.")
                        refresh_all_caches()
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

            with col_bad:
                reject_reason = st.text_area(
                    "Причина отправки на доработку *",
                    key=f"reject_reason_{repair['id']}",
                    placeholder="Не затянуты болты, скрипит педаль…",
                )
                if st.button("🔄 На доработку", key=f"reject_{repair['id']}"):
                    try:
                        reject_repair(engine, repair_id=repair["id"], comment=reject_reason)
                        flash_success(f"Ремонт {bike_label} отправлен на доработку. Косяк зафиксирован.")
                        refresh_all_caches()
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))


# ---------------------------------------------------------------------------
# Статистика косяков
# ---------------------------------------------------------------------------

def _section_stats(stats: list[dict]) -> None:
    st.markdown("### Статистика доработок по мастерам")

    if not stats:
        st.info("Пока нет завершённых или проверяемых ремонтов.")
        return

    for row in stats:
        name = full_name({"first_name": row.get("first_name"), "last_name": row.get("last_name")})
        total     = int(row.get("total_repairs") or 0)
        reworks   = int(row.get("repairs_with_rework") or 0)
        total_rw  = int(row.get("total_reworks") or 0)
        quality   = round((1 - reworks / total) * 100) if total else 100

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Мастер", name)
        col2.metric("Всего ремонтов", total)
        col3.metric("С косяками", reworks)
        col4.metric("Качество", f"{quality}%")
        st.divider()
