"""
role_workshop.py — кабинет мастера цеха.
"""

from datetime import datetime

import streamlit as st
from db import (
    consume_storage_stock,
    create_detail_repair_record,
    create_new_bike,
    ensure_workshop_repair,
    finish_repair,
    postpone_repair,
    refresh_all_caches,
    submit_for_review,
    text,
    update_bike_identity,
)
from ui import (
    flash_success,
    metric_card,
    render_empty,
    render_record_card,
    role_hero,
    section_switcher,
)
from utils import (
    aggregate_stock_by_part,
    filter_bikes,
    format_dt,
    full_name,
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
        metric_card("Свободных велосипедов", str(len(free_bikes)), "Свободные велосипеды")
    with b:
        metric_card("Наш парк", str(len(bikes)), "Весь велосипедный парк")
    with c:
        metric_card("Ожидают ремонта", str(len(waiting_repair)), "Ожидают ремонта")

    extra_a, extra_b, extra_c = st.columns(3)
    with extra_a:
        metric_card("Собрано велосипедов", str(len(built_bikes)), "Завершённые сборки")
    with extra_b:
        metric_card("Отремонтировано велосипедов", str(len(repaired_bikes)), "Внутренний ремонт")
    with extra_c:
        metric_card("Отремонтировано деталей", str(len(repaired_details)), "Аккумуляторы и мотор-колёса")

    section = section_switcher("workshop_section", ["Список велосипедов", "Сборка нового", "Ремонт деталей", "Продуктивность"])

    if section == "Список велосипедов":
        _workshop_bikes(bikes, repairs, workshop_stock, work_types, bike_by_id, current_user, engine)
    elif section == "Сборка нового":
        _workshop_new_bike(current_user, engine)
    elif section == "Ремонт деталей":
        _workshop_detail_repair(workshop_stock, current_user, engine)
    else:
        _workshop_productivity(current_user, productivity, my_completed_repairs, built_bikes, repaired_bikes, repaired_details, parts_used)


# ---------------------------------------------------------------------------

def _workshop_bikes(bikes, repairs, workshop_stock, work_types, bike_by_id, current_user, engine):
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
                consumed_stock_rows.append({
                    "spare_part_catalog_id": int(stock_row["spare_part_catalog_id"]),
                    "quantity": int(qty),
                    "spare_name": stock_row.get("spare_name") or "Запчасть",
                })

            comment = st.text_area("Комментарий по ремонту", height=90, key=f"workshop_comment_{active_workshop_bike['id']}")
            selected_action = st.radio(
                "Что делаем",
                ["Взять / сохранить в ремонте", "Готово к проверке", "Отложить"],
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

                if selected_action == "Готово к проверке":
                    if final_comment:
                        with engine.begin() as conn:
                            conn.execute(
                                text(
                                    "UPDATE repair_request SET comment = :c, updated_at = :ts WHERE id = :id"
                                ),
                                {"c": final_comment, "ts": datetime.now(), "id": repair_id},
                            )
                    submit_for_review(engine, repair_id=repair_id)
                    flash_success(f"Велосипед #{active_workshop_bike['id']} отправлен на проверку старшему мастеру.")
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


def _workshop_new_bike(current_user, engine):
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


def _workshop_detail_repair(workshop_stock, current_user, engine):
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
            consumable_rows.append({
                "spare_part_catalog_id": int(stock_row["spare_part_catalog_id"]),
                "quantity": int(qty),
            })
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


def _workshop_productivity(current_user, productivity, my_completed_repairs, built_bikes, repaired_bikes, repaired_details, parts_used):
    st.markdown('<div class="section-title">Продуктивность</div>', unsafe_allow_html=True)
    me = next((row for row in productivity if row.get("id") == current_user["id"]), None)
    if not me:
        render_empty("Данных по продуктивности пока нет.")
        return

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
                parts_line = ", ".join(
                    f"{row.get('spare_name') or row.get('article')} ({row.get('quantity_used')})"
                    for row in used_parts
                ) or "без деталей"
                st.markdown(
                    f"- {format_dt(repair.get('updated_at'))} · "
                    f"{repair.get('gov_number') or repair.get('serial_number') or '—'} · "
                    f"{repair.get('comment') or repair.get('type') or 'Работа'} · {parts_line}"
                )
        else:
            render_empty("У этого мастера пока нет завершённых работ.")
