"""
role_field_master.py — кабинет выездного мастера.
"""

from datetime import datetime, timedelta

import streamlit as st

from docs import generate_logistics_doc_bytes, logistics_doc_filename

from config import ACTIVE_MASTER_STATUSES
from db import (
    complete_logistics_request,
    consume_master_stock_by_catalog,
    finish_repair,
    finish_repair_with_replacement,
    finish_repair_with_vyvoz,
    postpone_repair,
    refresh_all_caches,
    return_master_stock_by_catalog_id,
    start_repair,
    transfer_catalog_stock_to_master,
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
    aggregate_stock_by_part,
    count_by,
    format_dt,
    format_short_date,
    full_name,
    sort_field_master_repairs,
    suggested_spare_parts_for_repair,
)


def field_master_dashboard(
    current_user: dict,
    repairs: list[dict],
    bikes: list[dict],
    stock: list[dict],
    master_stock: list[dict],
    parts_used: list[dict],
    work_types: list[dict],
    spare_catalog: list[dict],
    logistics: list[dict],
    engine,
) -> None:
    my_repairs = sort_field_master_repairs([row for row in repairs if row.get("assigned_to") == current_user["id"]])
    active_repairs = sort_field_master_repairs([row for row in my_repairs if row.get("status") in ACTIVE_MASTER_STATUSES])
    completed_repairs = sort_field_master_repairs([row for row in my_repairs if row.get("status") == "завершена"])
    replacement_repairs = [row for row in my_repairs if row.get("status") == "замена вело"]
    waiting_repairs = [row for row in my_repairs if row.get("status") in {"отложена", "ожидает запчасти"}]
    my_trunk_stock = [row for row in master_stock if row.get("master_id") == current_user["id"] and int(row.get("quantity") or 0) > 0]
    free_bikes = [bike for bike in bikes if bike.get("location_status") == "Свободен" and bike.get("tech_status") == "Исправен"]

    _trunk_by_cid: dict[int, dict] = {}
    for _r in my_trunk_stock:
        _cid = _r.get("spare_part_catalog_id")
        if _cid is None:
            continue
        if _cid not in _trunk_by_cid:
            _trunk_by_cid[_cid] = {"spare_part_catalog_id": _cid, "spare_name": _r.get("spare_name") or "—", "quantity": 0}
        _trunk_by_cid[_cid]["quantity"] += int(_r.get("quantity") or 0)
    trunk_aggregated = sorted(
        [v for v in _trunk_by_cid.values() if v["quantity"] > 0],
        key=lambda r: (r.get("spare_name") or "").lower(),
    )
    trunk_catalog_ids = {item["spare_part_catalog_id"] for item in trunk_aggregated}

    role_hero(
        "Выездной мастер",
        "Назначенные заявки, управление багажником и история выполненных работ.",
        f"Текущий пользователь: {full_name(current_user)}",
        "Открывайте заявки для выполнения, берите запчасти со склада в багажник и оформляйте вывоз или замену велосипеда.",
    )

    top = st.columns(5)
    stats = [
        ("Назначены", len([row for row in my_repairs if row.get("status") == "назначена"])),
        ("В работе", len([row for row in my_repairs if row.get("status") == "в работе"])),
        ("Ожидают", len(waiting_repairs)),
        ("На замену", len(replacement_repairs)),
        ("Завершены", len(completed_repairs)),
    ]
    for column, (label, value) in zip(top, stats):
        with column:
            metric_card(label, str(value), "Мои заявки")

    my_logistics = [
        lr for lr in logistics
        if lr.get("assigned_to") == current_user["id"]
        and lr.get("status") != "выполнена"
    ]

    section = section_switcher("field_master_section", ["Заявки", "Маршрут", "Логистика", "Запчасти", "Выполненные"])

    if section == "Заявки":
        _field_master_repairs(
            active_repairs, repairs, trunk_aggregated, trunk_catalog_ids,
            spare_catalog, work_types, free_bikes, current_user, engine,
        )
    elif section == "Маршрут":
        _field_master_route(active_repairs)
    elif section == "Логистика":
        _field_master_logistics(my_logistics, bikes, current_user, engine)
    elif section == "Запчасти":
        _field_master_parts(trunk_aggregated, stock, current_user, engine)
    else:
        _field_master_completed(completed_repairs, parts_used)


# ---------------------------------------------------------------------------

def _field_master_repairs(
    active_repairs, repairs, trunk_aggregated, trunk_catalog_ids,
    spare_catalog, work_types, free_bikes, current_user, engine,
):
    st.markdown('<div class="section-title">Мои заявки</div>', unsafe_allow_html=True)
    render_pills(count_by(active_repairs, "status"), red_keys=("назначена", "в работе", "отложена", "замена вело"))

    filter_cols = st.columns(2)
    status_filter_options = ["Все", "назначена", "в работе", "отложена", "ожидает запчасти", "замена вело"]
    darkstore_filter_options = ["Все"] + sorted({row.get("darkstore_name") or "—" for row in active_repairs})
    selected_status = filter_cols[0].selectbox("Статус", status_filter_options, key="field_master_status_filter")
    selected_darkstore = filter_cols[1].selectbox("Даркстор", darkstore_filter_options, key="field_master_darkstore_filter")

    filtered_active = [
        row for row in active_repairs
        if (selected_status == "Все" or (row.get("status") or "—") == selected_status)
        and (selected_darkstore == "Все" or (row.get("darkstore_name") or "—") == selected_darkstore)
    ]

    if not filtered_active:
        render_empty("Активных заявок нет.")

    for repair in filtered_active:
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
            ],
        )
        with st.expander("Открыть заявку"):
            st.markdown(f"**Велосипед:** {repair.get('serial_number') or '—'} / {repair.get('gov_number') or '—'}")
            st.markdown(f"**Проблема:** {repair.get('problem') or '—'}")
            if repair.get("assignment_comment"):
                st.markdown(f"**Комментарий диспетчера:** {repair['assignment_comment']}")

            bike_repairs = [row for row in repairs if row.get("bike_id") == repair.get("bike_id") and row["id"] != repair["id"]]
            if bike_repairs:
                st.markdown("**История работ по велосипеду**")
                for row in bike_repairs[:5]:
                    st.markdown(f"- {row.get('type') or '—'} · {row.get('status') or '—'} · {format_short_date(row.get('updated_at'))}")

            if repair.get("status") == "назначена":
                if st.button("Взять в работу", key=f"start_repair_{repair['id']}", type="primary", use_container_width=True):
                    try:
                        start_repair(engine, repair_id=repair["id"])
                        refresh_all_caches()
                        flash_success(f"Заявка #{repair.get('incoming_id') or repair['id']} взята в работу.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

            in_trunk = [
                item for item in suggested_spare_parts_for_repair(repair, spare_catalog)
                if int(item.get("id") or 0) in trunk_catalog_ids
            ]
            missing = [
                item for item in suggested_spare_parts_for_repair(repair, spare_catalog)
                if int(item.get("id") or 0) not in trunk_catalog_ids
            ]
            if in_trunk:
                st.markdown("**В багажнике есть нужные запчасти:**")
                for item in in_trunk:
                    st.markdown(f"- {item.get('name') or 'Запчасть'} ✓")
            if missing:
                st.markdown("**Отсутствует в багажнике:**")
                for item in missing:
                    st.markdown(f"- {item.get('name') or 'Запчасть'}")
                st.caption("Добавьте недостающее во вкладке «Запчасти».")

            st.divider()
            st.markdown("**Выполнение**")

            consumed_parts: list[dict] = []
            if trunk_aggregated:
                st.markdown("Запчасти из багажника:")
                for part_row in trunk_aggregated:
                    cols = st.columns([6, 2])
                    cols[0].markdown(f"**{part_row.get('spare_name') or 'Запчасть'}** · {part_row['quantity']} шт.")
                    qty = cols[1].number_input(
                        "шт.",
                        min_value=0,
                        max_value=part_row["quantity"],
                        value=0,
                        step=1,
                        key=f"consume_qty_{repair['id']}_{part_row['spare_part_catalog_id']}",
                        label_visibility="collapsed",
                    )
                    consumed_parts.append({
                        "spare_part_catalog_id": part_row["spare_part_catalog_id"],
                        "quantity": int(qty),
                    })
            else:
                st.caption("Багажник пуст. Добавьте запчасти во вкладке «Запчасти» перед выездом.")

            work_labels = [row.get("name") for row in work_types]
            selected_works = st.multiselect("Выполненные работы", work_labels, key=f"works_{repair['id']}")
            comment = st.text_area("Комментарий мастера", height=80, key=f"comment_{repair['id']}")

            selected_action = st.radio(
                "Действие",
                ["Завершить", "Отложить", "Вывезти велосипед", "Заменить велосипед"],
                horizontal=True,
                key=f"repair_action_{repair['id']}",
            )
            postpone_reason = ""
            replacement_bike_id = None
            if selected_action == "Отложить":
                postpone_reason = st.text_input("Причина откладывания", key=f"postpone_reason_{repair['id']}")
            elif selected_action == "Заменить велосипед":
                if free_bikes:
                    free_bike_labels = {
                        f"{b.get('serial_number') or b['id']} / {b.get('gov_number') or '—'} · {b.get('model') or '—'}": b
                        for b in free_bikes
                    }
                    selected_bike_label = st.selectbox(
                        "Велосипед для замены",
                        list(free_bike_labels.keys()),
                        key=f"replacement_bike_{repair['id']}",
                    )
                    replacement_bike_id = free_bike_labels[selected_bike_label]["id"]
                else:
                    st.warning("Нет свободных исправных велосипедов для замены.")

            # --- Превью отчёта ---
            preview_parts = [p for p in consumed_parts if int(p.get("quantity") or 0) > 0]
            if preview_parts or selected_works or (comment and comment.strip()):
                with st.container():
                    st.caption("📋 Что войдёт в отчёт:")
                    if selected_works:
                        st.caption(f"Работы: {', '.join(selected_works)}")
                    if preview_parts:
                        part_labels = []
                        for p in preview_parts:
                            name = next(
                                (t.get("spare_name") for t in trunk_aggregated
                                 if t["spare_part_catalog_id"] == p["spare_part_catalog_id"]),
                                "Запчасть"
                            )
                            part_labels.append(f"{name} × {p['quantity']}")
                        st.caption(f"Запчасти: {', '.join(part_labels)}")
                    if comment and comment.strip():
                        st.caption(f"Комментарий: {comment.strip()}")

            if st.button("Применить", key=f"apply_repair_{repair['id']}", type="primary", use_container_width=True):
                try:
                    for item in consumed_parts:
                        qty = int(item.get("quantity") or 0)
                        if qty <= 0:
                            continue
                        consume_master_stock_by_catalog(
                            engine,
                            spare_part_catalog_id=int(item["spare_part_catalog_id"]),
                            master_id=current_user["id"],
                            repair_request_id=repair["id"],
                            quantity=qty,
                        )

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
                    elif selected_action == "Вывезти велосипед":
                        finish_repair_with_vyvoz(engine, repair_id=repair["id"], comment=final_comment)
                        flash_success(f"Велосипед вывезен. Заявка #{repair.get('incoming_id') or repair['id']} закрыта.")
                    else:
                        if replacement_bike_id is None:
                            raise ValueError("Выберите велосипед для замены.")
                        finish_repair_with_replacement(
                            engine,
                            repair_id=repair["id"],
                            replacement_bike_id=replacement_bike_id,
                            comment=final_comment,
                        )
                        flash_success(f"Замена выполнена. Заявка #{repair.get('incoming_id') or repair['id']} закрыта.")

                    refresh_all_caches()
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def _field_master_parts(trunk_aggregated, stock, current_user, engine):
    st.markdown('<div class="section-title">Запчасти</div>', unsafe_allow_html=True)

    st.markdown("### Мой багажник")
    if trunk_aggregated:
        for row in trunk_aggregated:
            col_a, col_b = st.columns([6, 1])
            col_a.markdown(f"**{row.get('spare_name') or '—'}**")
            col_b.markdown(f"`{row['quantity']} шт.`")
    else:
        render_empty("Багажник пуст.")

    aggregated_stock = aggregate_stock_by_part([row for row in stock if int(row.get("quantity") or 0) > 0])

    st.markdown("### Взять со склада")
    if aggregated_stock:
        if "field_master_take_row_ids" not in st.session_state:
            st.session_state["field_master_take_row_ids"] = [0]
        take_row_ids = list(st.session_state["field_master_take_row_ids"])
        part_options = {
            f"{row.get('spare_name') or 'Запчасть'} · {int(row.get('quantity') or 0)} шт.": row
            for row in aggregated_stock
        }
        option_labels = list(part_options.keys())
        take_lines: list[dict] = []
        for row_id in take_row_ids:
            cols = st.columns([7, 2, 1])
            selected_label = cols[0].selectbox("Запчасть", option_labels, key=f"take_part_label_{row_id}", label_visibility="collapsed")
            selected_item = part_options[selected_label]
            qty = cols[1].number_input(
                "шт.",
                min_value=0,
                max_value=max(int(selected_item.get("quantity") or 0), 0),
                value=0,
                step=1,
                key=f"take_part_qty_{row_id}",
                label_visibility="collapsed",
            )
            if cols[2].button("✕", key=f"take_remove_{row_id}", use_container_width=True):
                st.session_state["field_master_take_row_ids"] = [rid for rid in take_row_ids if rid != row_id] or [0]
                st.rerun()
            take_lines.append({
                "spare_part_catalog_id": int(selected_item["spare_part_catalog_id"]),
                "quantity": int(qty),
            })

        add_col, confirm_col = st.columns([1, 4])
        if add_col.button("+ Строка", key="field_master_add_take_row", use_container_width=True):
            next_id = max(take_row_ids) + 1
            st.session_state["field_master_take_row_ids"] = take_row_ids + [next_id]
            st.rerun()
        if confirm_col.button("Взять в багажник", key="confirm_take_to_trunk", type="primary", use_container_width=True):
            try:
                to_take = [item for item in take_lines if item["quantity"] > 0]
                if not to_take:
                    raise ValueError("Укажите хотя бы одну запчасть и количество больше нуля.")
                for item in to_take:
                    transfer_catalog_stock_to_master(
                        engine,
                        master_id=current_user["id"],
                        spare_part_catalog_id=item["spare_part_catalog_id"],
                        quantity=item["quantity"],
                    )
                refresh_all_caches()
                flash_success("Запчасти добавлены в багажник.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    else:
        render_empty("На складе нет остатков.")

    st.markdown("### Вернуть на склад")
    if trunk_aggregated:
        trunk_label_map = {
            f"{row.get('spare_name') or 'Запчасть'} · {row['quantity']} шт.": row
            for row in trunk_aggregated
        }
        with st.form("return_parts_from_trunk_form"):
            return_label = st.selectbox("Запчасть из багажника", list(trunk_label_map.keys()))
            selected_return_row = trunk_label_map[return_label]
            return_qty = st.number_input(
                "Количество",
                min_value=0,
                max_value=selected_return_row["quantity"],
                value=0,
                step=1,
            )
            return_clicked = st.form_submit_button("Вернуть на склад", use_container_width=True)

        if return_clicked:
            try:
                if return_qty <= 0:
                    raise ValueError("Укажите количество больше нуля.")
                return_master_stock_by_catalog_id(
                    engine,
                    spare_part_catalog_id=selected_return_row["spare_part_catalog_id"],
                    master_id=current_user["id"],
                    quantity=return_qty,
                )
                refresh_all_caches()
                flash_success("Запчасти возвращены на склад.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    else:
        render_empty("Багажник пуст, нечего возвращать.")


def _field_master_completed(completed_repairs: list[dict], parts_used: list[dict]) -> None:
    st.markdown('<div class="section-title">Выполненные заявки</div>', unsafe_allow_html=True)

    if not completed_repairs:
        render_empty("Пока нет завершенных заявок.")
        return

    # --- Фильтр по периоду ---
    period = st.radio(
        "Период", ["Сегодня", "Неделя", "Все"], horizontal=True, key="completed_period"
    )
    today = datetime.now().date()
    if period == "Сегодня":
        cutoff = today
    elif period == "Неделя":
        cutoff = today - timedelta(days=6)
    else:
        cutoff = None

    def _repair_date(r: dict):
        v = r.get("updated_at")
        if v is None:
            return None
        if hasattr(v, "date"):
            return v.date()
        try:
            from datetime import datetime as _dt
            return _dt.fromisoformat(str(v)).date()
        except Exception:
            return None

    if cutoff:
        shown = [r for r in completed_repairs if (_d := _repair_date(r)) and _d >= cutoff]
    else:
        shown = completed_repairs

    # --- Сводка ---
    parts_for_shown: list[dict] = []
    for r in shown:
        parts_for_shown.extend([p for p in parts_used if p.get("repair_request_id") == r["id"]])
    total_parts_qty = sum(int(p.get("quantity_used") or 0) for p in parts_for_shown)
    col1, col2, col3 = st.columns(3)
    col1.metric("Ремонтов завершено", len(shown))
    col2.metric("Запчастей использовано", total_parts_qty)
    col3.metric("С комментарием", sum(1 for r in shown if r.get("comment")))

    if not shown:
        st.info("За этот период нет завершённых заявок.")
        return

    st.divider()

    # --- Список ---
    for repair in shown:
        used_parts = [row for row in parts_used if row.get("repair_request_id") == repair["id"]]
        parts_str = (
            ", ".join(
                f"{row.get('spare_name') or row.get('article')} × {row.get('quantity_used')}"
                for row in used_parts
            ) or "—"
        )
        render_record_card(
            title=f"Работа #{repair['id']} · {repair.get('gov_number') or repair.get('serial_number') or '—'}",
            subtitle=f"{repair.get('darkstore_name') or '—'} · {format_short_date(repair.get('updated_at'))}",
            status=repair.get("status") or "—",
            fields=[
                ("Модель",       repair.get("model") or "—"),
                ("Тип работы",   repair.get("type") or "—"),
                ("Комментарий",  repair.get("comment") or "—"),
                ("Запчасти",     parts_str),
            ],
        )


def _field_master_logistics(my_logistics: list[dict], bikes: list[dict], current_user: dict, engine) -> None:
    st.markdown('<div class="section-title">Логистика</div>', unsafe_allow_html=True)

    if not my_logistics:
        render_empty("Нет назначенных задач по логистике.")
        return

    bike_by_id = {b["id"]: b for b in bikes}

    for lr in my_logistics:
        rtype_label = "🔼 Поставка" if lr["request_type"] == "поставка" else "🔽 Вывоз"
        bike_ids = lr.get("bike_ids") or []
        bike_lines = []
        for bid in bike_ids:
            b = bike_by_id.get(bid)
            if b:
                bike_lines.append(f"{b.get('gov_number') or b.get('serial_number') or bid} · {b.get('model') or '—'}")
            else:
                bike_lines.append(f"Байк #{bid}")

        render_record_card(
            title=f"{rtype_label} · {lr.get('darkstore_name') or '—'}",
            subtitle=f"Статус: {lr.get('status') or '—'} · Байков: {len(bike_ids)}",
            status=lr.get("status") or "новая",
            fields=[
                ("Байки", ", ".join(bike_lines) or "—"),
                ("Примечание", lr.get("notes") or "—"),
                ("Создана", format_dt(lr.get("created_at"))),
            ],
        )

        with st.expander(f"Завершить #{lr['id']}"):
            st.markdown("**Байки в этой задаче:**")
            for line in bike_lines:
                st.markdown(f"- {line}")

            # Скачать акт
            try:
                bikes_in_req = [b for b in bikes if b["id"] in (lr.get("bike_ids") or [])]
                master_full = f"{lr.get('master_first_name') or ''} {lr.get('master_last_name') or ''}".strip()
                doc_bytes = generate_logistics_doc_bytes(
                    lr,
                    bikes_in_req,
                    darkstore_name=lr.get("darkstore_name") or "",
                    master_name=master_full or full_name(current_user),
                )
                st.download_button(
                    label="📄 Скачать акт (.docx)",
                    data=doc_bytes,
                    file_name=logistics_doc_filename(lr),
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"fm_log_dl_{lr['id']}",
                )
            except Exception as exc:
                st.caption(f"Документ недоступен: {exc}")

            if st.button("Отметить выполненной", key=f"fm_log_done_{lr['id']}", type="primary"):
                try:
                    complete_logistics_request(engine, logistics_id=lr["id"])
                    refresh_all_caches()
                    flash_success(f"Задача #{lr['id']} выполнена.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


# ---------------------------------------------------------------------------
# Маршрут дня — планирование + ссылка на Яндекс.Карты
# ---------------------------------------------------------------------------

def _field_master_route(active_repairs: list[dict]) -> None:
    st.markdown('<div class="section-title">Маршрут дня</div>', unsafe_allow_html=True)
    st.caption(
        "Выберите заявки в нужном порядке — маршрут начинается от цеха. "
        "Для изменения порядка выбирайте адреса последовательно."
    )

    workshop_default = st.session_state.get("workshop_address_default", "")
    workshop_addr = st.text_input(
        "Начальная точка (адрес цеха)",
        value=workshop_default,
        placeholder="Москва, ул. Примерная, 1",
        key="route_workshop_addr",
    )
    if workshop_addr:
        st.session_state["workshop_address_default"] = workshop_addr

    # Собрать уникальные точки из активных заявок
    stop_options: list[dict] = []
    seen_addrs: set[str] = set()
    for r in active_repairs:
        addr = (r.get("full_address") or "").strip()
        if not addr:
            # Fallback: darkstore name
            addr = r.get("darkstore_name") or ""
        if not addr or addr in seen_addrs:
            continue
        seen_addrs.add(addr)
        label_parts = [addr]
        ds = r.get("darkstore_name")
        if ds and ds not in addr:
            label_parts.append(f"({ds})")
        stop_options.append({
            "addr": addr,
            "label": " ".join(label_parts),
            "repair_id": r.get("id"),
        })

    if not stop_options:
        st.info("Нет активных заявок с адресами для построения маршрута.")
        return

    all_labels = [s["label"] for s in stop_options]
    selected_labels = st.multiselect(
        "Добавить точки в маршрут (в нужном порядке)",
        all_labels,
        key="route_stops",
        help="Выбирайте адреса последовательно — первый выбранный = первая остановка.",
    )

    if not selected_labels:
        st.info("Выберите хотя бы одну точку для построения маршрута.")
        return

    # Показать итоговый маршрут
    st.markdown("---")
    st.markdown("**Маршрут:**")
    stops_in_order = [workshop_addr or "Цех"] + selected_labels
    for i, stop in enumerate(stops_in_order):
        icon = "🏭" if i == 0 else f"{i}."
        st.markdown(f"{icon} {stop}")

    # Построить URL Яндекс.Карт
    import urllib.parse

    def _build_yandex_url(stops: list[str]) -> str:
        # rtext формат: адрес1~адрес2~...
        parts = [urllib.parse.quote(s, safe="") for s in stops]
        rtext = "~".join(parts)
        return f"https://yandex.ru/maps/?rtext={rtext}&rtt=auto&mode=routes"

    addr_stops = [workshop_addr] + [
        next(s["addr"] for s in stop_options if s["label"] == lbl)
        for lbl in selected_labels
    ]
    yandex_url = _build_yandex_url(addr_stops)

    st.markdown(
        f'''<a href="{yandex_url}" target="_blank" style="
            display:inline-block; padding:10px 20px; background:#fc3f1d;
            color:white; font-weight:bold; border-radius:8px;
            text-decoration:none; font-size:15px;">
            🗺️ Открыть в Яндекс.Картах
        </a>''',
        unsafe_allow_html=True,
    )
    st.caption(f"Ссылка: {yandex_url}")
