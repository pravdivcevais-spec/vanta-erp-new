"""
role_curator.py — кабинет куратора / даркстора.
"""

from datetime import datetime

import streamlit as st

from config import DONE_REQUEST_STATUSES
from db import (
    cancel_incoming_request_by_curator,
    create_incoming_request,
    rate_incoming_request,
    refresh_all_caches,
    update_incoming_request_problem,
)
from ui import (
    flash_success,
    metric_card,
    render_empty,
    render_pills,
    render_record_card,
    role_hero,
    section_switcher,
)
from utils import (
    bike_history_for_darkstore,
    bike_logs_for_bike,
    count_by,
    filter_bikes,
    format_dt,
    format_short_date,
    latest_assignment_name,
)


def _build_curator_bike_label(bike: dict, open_request_bike_ids: set) -> str:
    parts = [
        bike.get("gov_number") or "Без гос номера",
        bike.get("serial_number") or f"Bike #{bike['id']}",
        bike.get("tech_status") or "—",
    ]
    if bike["id"] in open_request_bike_ids:
        parts.append("уже есть заявка")
    return " · ".join(parts)


def curator_dashboard(
    darkstore: dict,
    incoming_requests: list[dict],
    bikes: list[dict],
    bike_logs: list[dict],
    rentals: list[dict],
    engine,
) -> None:
    ds_requests = [row for row in incoming_requests if row.get("darkstore_id") == darkstore["id"]]
    ds_bikes = [row for row in bikes if row.get("darkstore_id") == darkstore["id"]]
    active_rental_by_bike = {
        int(row["bike_id"]): row
        for row in rentals
        if row.get("status") == "активна" and row.get("bike_id") is not None
    }
    open_requests = [row for row in ds_requests if row.get("status") not in DONE_REQUEST_STATUSES]
    open_request_bike_ids = {
        row.get("bike_id")
        for row in ds_requests
        if row.get("status") not in DONE_REQUEST_STATUSES and row.get("bike_id")
    }

    role_hero(
        "Куратор / Даркстор",
        "Рабочее место для контроля парка и заявок по одной точке.",
        f"Даркстор {darkstore.get('name')} · направление {darkstore.get('direction') or 'не указано'}",
        "Куратор видит только свой парк, свои заявки и действия по созданию новой заявки.",
    )

    left, right = st.columns(2)
    with left:
        metric_card("Велосипедов в парке", str(len(ds_bikes)), "Все велосипеды этого даркстора")
    with right:
        metric_card("Заявок висит", str(len(open_requests)), "Новые, назначенные и в работе")

    screen = section_switcher("curator_section", ["Мой парк", "Мои заявки", "Создать заявку"])

    if screen == "Мой парк":
        _curator_park(darkstore, ds_bikes, incoming_requests, bike_logs, active_rental_by_bike, open_request_bike_ids, engine)
    elif screen == "Мои заявки":
        _curator_requests(ds_requests, engine)
    else:
        _curator_create(darkstore, ds_bikes, open_request_bike_ids, engine)


# ---------------------------------------------------------------------------

def _curator_park(
    darkstore, ds_bikes, incoming_requests, bike_logs, active_rental_by_bike, open_request_bike_ids, engine
):
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
        rental = active_rental_by_bike.get(int(bike["id"]))
        if rental:
            start = rental.get("start_dt")
            if isinstance(start, str):
                try:
                    start = datetime.fromisoformat(start)
                except ValueError:
                    start = None
            days_on_darkstore = max((datetime.now().date() - start.date()).days, 0) if start else 0
        else:
            days_on_darkstore = 0

        render_record_card(
            title=title,
            subtitle=subtitle,
            status=bike.get("tech_status") or "—",
            fields=[
                ("IoT", bike.get("iot_device_id") or "—"),
                ("Серийный номер", bike.get("serial_number") or "—"),
                ("Модель", bike.get("model") or "—"),
                ("Дней на дарке", days_on_darkstore),
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


def _curator_requests(ds_requests, engine):
    st.markdown('<div class="section-title">Мои заявки</div>', unsafe_allow_html=True)
    render_pills(count_by(ds_requests, "status"), red_keys=("новая", "назначена", "в работе"))
    if not ds_requests:
        render_empty("По этому даркстору пока нет заявок.")

    for row in ds_requests:
        row_status = row.get("status") or ""
        render_record_card(
            title=f"Заявка #{row['id']}",
            subtitle=f"{format_dt(row.get('created_at'))} · устройство: {row.get('device_type') or row.get('request_type') or '—'}",
            status=row_status or "—",
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
            st.markdown(f"**Велосипед:** {row.get('serial_number') or '—'}")
            st.markdown(f"**Назначена на:** {latest_assignment_name(row)}")

            if row_status == "новая":
                st.caption("Заявка ещё не назначена мастеру.")
                with st.form(f"curator_edit_request_{row['id']}"):
                    new_problem = st.text_area(
                        "Описание проблемы", value=row.get("problem") or "", height=100,
                        key=f"curator_problem_text_{row['id']}",
                    )
                    col_save, col_cancel = st.columns(2)
                    save_clicked = col_save.form_submit_button("Сохранить изменение", use_container_width=True)
                    cancel_clicked = col_cancel.form_submit_button("Отменить заявку", use_container_width=True)

                if save_clicked:
                    try:
                        if not new_problem.strip():
                            raise ValueError("Описание проблемы не может быть пустым.")
                        update_incoming_request_problem(engine, incoming_id=row["id"], problem=new_problem.strip())
                        refresh_all_caches()
                        flash_success("Описание проблемы обновлено.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

                if cancel_clicked:
                    try:
                        cancel_incoming_request_by_curator(engine, incoming_id=row["id"])
                        refresh_all_caches()
                        flash_success(f"Заявка #{row['id']} отменена.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

            elif row_status == "завершена":
                existing_rating = row.get("rr_client_rating")
                if existing_rating:
                    stars = "★" * int(existing_rating) + "☆" * (5 - int(existing_rating))
                    st.success(f"Ваша оценка: {stars} ({existing_rating}/5)")
                else:
                    st.caption("Оцените качество ремонта:")
                    star_value = st.feedback("stars", key=f"curator_stars_{row['id']}")
                    if star_value is not None:
                        if st.button("Сохранить оценку", key=f"curator_save_rating_{row['id']}", type="primary", use_container_width=True):
                            try:
                                rate_incoming_request(engine, incoming_id=row["id"], rating=star_value + 1)
                                refresh_all_caches()
                                flash_success(f"Оценка {star_value + 1}/5 сохранена.")
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))


def _curator_create(darkstore, ds_bikes, open_request_bike_ids, engine):
    st.markdown('<div class="section-title">Создать заявку</div>', unsafe_allow_html=True)
    prefilled_bike_id = st.session_state.pop("curator_prefill_bike_id", None)
    bike_options = {_build_curator_bike_label(bike, open_request_bike_ids): bike["id"] for bike in ds_bikes}
    prefilled_label = next((label for label, bid in bike_options.items() if bid == prefilled_bike_id), None)

    with st.form("curator_create_request_form", clear_on_submit=True):
        device_type = st.selectbox("Тип устройства", ["Велосипед", "Аккумулятор", "Зарядное устройство"], index=0)
        bike_label = None
        if device_type == "Велосипед":
            labels = list(bike_options.keys())
            default_index = labels.index(prefilled_label) if prefilled_label in labels else 0
            bike_label = st.selectbox("Велосипед", labels, index=default_index if labels else None)
        problem = st.text_area("Опишите проблему", height=120, placeholder="Что именно не работает или требует выезда мастера?")
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
                full_address=darkstore.get("name") or "",
            )
            refresh_all_caches()
            flash_success("Заявка успешно создана.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
