"""
role_dispatcher.py — кабинет диспетчера.
"""

from datetime import datetime

import streamlit as st

from docs import generate_logistics_doc_bytes, logistics_doc_filename

from config import ACTIVE_MASTER_STATUSES, EMPLOYEE_ROLE_MAP
from db import (
    assign_incoming_request,
    assign_logistics_request,
    cancel_logistics_request,
    complete_logistics_request,
    create_logistics_request,
    update_bike_gov_number,
    import_m4_xlsx,
    refresh_all_caches,
    update_incoming_request_type,
)
from ui import (
    compact_repair_card,
    compact_request_card,
    flash_success,
    metric_card,
    render_empty,
    render_record_card,
    role_hero,
    section_switcher,
)
from utils import (
    count_by,
    format_dt,
    full_name,
    latest_assignment_name,
)


def dispatcher_dashboard(
    current_user: dict,
    incoming_requests: list[dict],
    repairs: list[dict],
    bikes: list[dict],
    employees: list[dict],
    productivity: list[dict],
    parts_used: list[dict],
    darkstores: list[dict],
    logistics: list[dict],
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
        if row.get("status") in ACTIVE_MASTER_STATUSES:
            master_name = latest_assignment_name(row)
            master_workload[master_name] = master_workload.get(master_name, 0) + 1

    field_productivity = [row for row in productivity if row.get("id") in field_master_ids]
    productivity_map = {full_name(row): row for row in field_productivity}

    _now = datetime.now()
    _month_start = _now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    parts_by_master: dict[str, int] = {}
    cost_by_master_total: dict[str, float] = {}
    cost_by_master_month: dict[str, float] = {}
    part_names: dict[str, int] = {}
    repair_map = {row["id"]: row for row in repairs}
    for row in parts_used:
        repair = repair_map.get(row.get("repair_request_id"))
        if not repair or repair.get("assigned_to") not in field_master_ids:
            continue
        qty = int(row.get("quantity_used") or 0)
        price = float(row.get("price") or 0)
        cost = qty * price
        master_name = latest_assignment_name(repair)
        spare_name = row.get("spare_name") or row.get("article") or "Запчасть"
        parts_by_master[master_name] = parts_by_master.get(master_name, 0) + qty
        cost_by_master_total[master_name] = cost_by_master_total.get(master_name, 0.0) + cost
        part_names[spare_name] = part_names.get(spare_name, 0) + qty
        row_dt = row.get("created_at")
        if isinstance(row_dt, str):
            try:
                row_dt = datetime.fromisoformat(row_dt)
            except ValueError:
                row_dt = None
        if row_dt and row_dt >= _month_start:
            cost_by_master_month[master_name] = cost_by_master_month.get(master_name, 0.0) + cost

    total_cost_all = sum(cost_by_master_total.values())
    total_cost_month = sum(cost_by_master_month.values())
    bikes_in_rental = [b for b in bikes if b.get("location_status") == "В аренде"]
    avg_cost_per_rental_bike = total_cost_all / len(bikes_in_rental) if bikes_in_rental else 0.0

    ratings = [float(row.get("client_rating")) for row in field_master_repairs if row.get("client_rating") is not None]
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else 0

    def _repair_dt(row: dict):
        v = row.get("updated_at")
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v)
            except ValueError:
                return None
        return v

    ratings_month = [
        float(row.get("client_rating"))
        for row in field_master_repairs
        if row.get("client_rating") is not None
        and (_repair_dt(row) or datetime.min) >= _month_start
    ]
    avg_rating_month = round(sum(ratings_month) / len(ratings_month), 2) if ratings_month else 0

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
            subtitle="Только активные заявки (без завершённых)",
            status=f"{len(field_masters)} мастеров",
            fields=[(name, count) for name, count in sorted(master_workload.items(), key=lambda item: (-item[1], item[0]))[:6]] or [("Нет активных заявок", "0")],
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
            subtitle="Выездной контур: шт., стоимость за месяц / всего / ср. на вело",
            status=f"{sum(parts_by_master.values())} шт.",
            fields=(
                [
                    ("За этот месяц", f"{total_cost_month:,.0f} ₽"),
                    ("За всё время", f"{total_cost_all:,.0f} ₽"),
                    ("Ср. расход на вело в аренде", f"{avg_cost_per_rental_bike:,.0f} ₽"),
                ]
                + [
                    (name, f"{qty} шт. · {cost_by_master_total.get(name, 0):,.0f} ₽")
                    for name, qty in sorted(parts_by_master.items(), key=lambda item: (-item[1], item[0]))[:3]
                ]
            )[:6] or [("Нет списаний", "0")],
        )
        render_record_card(
            title="Оценка клиентов",
            subtitle="Средняя оценка выездных ремонтов: за месяц и за всё время",
            status=f"★ {avg_rating_month:.2f} / мес." if ratings_month else ("★ " + f"{avg_rating:.2f}" if ratings else "Нет оценок"),
            fields=[
                ("За этот месяц", f"★ {avg_rating_month:.2f} ({len(ratings_month)} оц.)" if ratings_month else "—"),
                ("За всё время", f"★ {avg_rating:.2f} ({len(ratings)} оц.)" if ratings else "—"),
            ],
        )
        render_record_card(
            title="Топ запчастей",
            subtitle="Самые часто используемые запчасти выездным контуром",
            status=f"{sum(part_names.values())} шт. всего",
            fields=[(name, f"{qty} шт.") for name, qty in sorted(part_names.items(), key=lambda item: (-item[1], item[0]))[:6]] or [("Нет данных", "0")],
        )

    section = section_switcher("dispatcher_section", ["Поток заявок", "Работы выездных", "Логистика", "Импорт M4"])

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
            haystack = " ".join([
                str(row.get("id") or ""),
                str(row.get("gov_number") or ""),
                str(row.get("darkstore_name") or ""),
                str(row.get("problem") or ""),
                str(row.get("model") or ""),
            ]).lower()
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
            compact_request_card(row, latest_assignment_name)
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

    elif section == "Работы выездных":
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
            compact_repair_card(repair, latest_assignment_name)
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

    elif section == "Логистика":
        _dispatcher_logistics(current_user, bikes, darkstores, field_masters, logistics, engine)

    else:
        _dispatcher_m4_import(engine)


# ---------------------------------------------------------------------------
# Логистика — вывозы и поставки
# ---------------------------------------------------------------------------

def _dispatcher_logistics(
    current_user: dict,
    bikes: list[dict],
    darkstores: list[dict],
    field_masters: list[dict],
    logistics: list[dict],
    engine,
) -> None:
    st.markdown('<div class="section-title">Логистика</div>', unsafe_allow_html=True)

    tab_new, tab_list = st.tabs(["Создать заявку", "Активные заявки"])

    # --- Показать акт созданной заявки (над табами, не теряется) ---
    if st.session_state.get("log_doc_pending"):
        doc_info = st.session_state.pop("log_doc_pending")
        st.success("Заявка создана! Скачайте акт:")
        st.download_button(
            label="📄 Скачать акт созданной заявки (.docx)",
            data=doc_info["bytes"],
            file_name=doc_info["name"],
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="log_dl_new",
            type="primary",
        )
        st.divider()

    # --- Создание заявки ---
    with tab_new:

        darkstore_map = {ds["name"]: ds["id"] for ds in darkstores}
        rtype = st.radio("Тип", ["вывоз", "поставка", "замена"], horizontal=True, key="log_rtype")

        selected_ds_name = st.selectbox("Даркстор", list(darkstore_map.keys()), key="log_ds")
        selected_ds_id = darkstore_map[selected_ds_name]

        # Пул байков для выбора
        darkstore_bikes = [
            b for b in bikes
            if b.get("darkstore_id") == selected_ds_id and b.get("location_status") == "В аренде"
        ]
        stock_bikes = [
            b for b in bikes
            if b.get("location_status") == "Свободен" and b.get("tech_status") == "Исправен"
        ]

        def _bike_label(b: dict) -> str:
            return f"{b.get('gov_number') or b.get('serial_number') or b['id']} · {b.get('model') or '—'}"

        master_label_map = {full_name(m): m["id"] for m in field_masters}
        selected_master = st.selectbox(
            "Назначить мастеру", ["— не назначать —"] + list(master_label_map.keys()), key="log_master"
        )
        notes = st.text_area("Примечание", height=80, key="log_notes")

        if rtype == "замена":
            st.caption("Замена: забрать старые байки с даркстора + привезти новые со склада.")
            col_out, col_in = st.columns(2)
            with col_out:
                if not darkstore_bikes:
                    st.info("Нет байков «В аренде» на этом дарксторе.")
                    vyvoz_ids = []
                else:
                    vyvoz_map = {_bike_label(b): b["id"] for b in darkstore_bikes}
                    vyvoz_sel = st.multiselect("Байки на вывоз (старые)", list(vyvoz_map.keys()), key="log_vyvoz")
                    vyvoz_ids = [vyvoz_map[l] for l in vyvoz_sel]
            with col_in:
                if not stock_bikes:
                    st.info("Нет байков на складе (Свободен + Исправен).")
                    postavka_ids = []
                else:
                    post_map = {_bike_label(b): b["id"] for b in stock_bikes}
                    post_sel = st.multiselect("Байки на поставку (новые)", list(post_map.keys()), key="log_postavka")
                    postavka_ids = [post_map[l] for l in post_sel]

            if st.button("Создать заявку на замену", type="primary", key="log_create_btn"):
                if not vyvoz_ids and not postavka_ids:
                    st.warning("Выберите байки хотя бы для одного направления.")
                else:
                    try:
                        lid = create_logistics_request(
                            engine,
                            request_type="замена",
                            darkstore_id=selected_ds_id,
                            notes=notes.strip(),
                            created_by=current_user["id"],
                            vyvoz_bike_ids=vyvoz_ids,
                            postavka_bike_ids=postavka_ids,
                        )
                        assigned_master_name = ""
                        if selected_master != "— не назначать —":
                            assign_logistics_request(
                                engine, logistics_id=lid,
                                assigned_to=master_label_map[selected_master],
                            )
                            assigned_master_name = selected_master
                        vyvoz_details = [b for b in darkstore_bikes if b["id"] in vyvoz_ids]
                        post_details  = [b for b in stock_bikes if b["id"] in postavka_ids]
                        fake_lr = {"id": lid, "request_type": "замена",
                                   "darkstore_name": selected_ds_name, "notes": notes.strip()}
                        doc_bytes = generate_logistics_doc_bytes(
                            fake_lr, [],
                            darkstore_name=selected_ds_name,
                            created_by_name=full_name(current_user),
                            master_name=assigned_master_name,
                            vyvoz_bikes=vyvoz_details,
                            postavka_bikes=post_details,
                        )
                        st.session_state["log_doc_pending"] = {
                            "bytes": doc_bytes,
                            "name": logistics_doc_filename(fake_lr),
                        }
                        refresh_all_caches()
                        flash_success(f"Заявка на замену создана (#{lid}). Скачайте акт выше.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
        else:
            if rtype == "вывоз":
                eligible = darkstore_bikes
                label = "Байки на дарксторе (В аренде)"
            else:
                eligible = stock_bikes
                label = "Байки на складе (Свободен + Исправен)"

            if not eligible:
                st.info(f"Нет доступных байков для {'вывоза с этого даркстора' if rtype == 'вывоз' else 'поставки (склад пуст)'}.")
            else:
                bike_label_map = {_bike_label(b): b["id"] for b in eligible}
                selected_labels = st.multiselect(label, list(bike_label_map.keys()), key="log_bikes")
                selected_bike_ids = [bike_label_map[l] for l in selected_labels]

                # Для поставки — поля гос номера для каждого выбранного байка
                gov_numbers: dict[int, str] = {}
                if rtype == "поставка" and selected_bike_ids:
                    st.markdown("**Гос номера для поставляемых байков:**")
                    for bid in selected_bike_ids:
                        bike_obj = next((b for b in eligible if b["id"] == bid), None)
                        if bike_obj:
                            cur_gn = bike_obj.get("gov_number") or ""
                            gn = st.text_input(
                                f"Гос номер — {bike_obj.get('serial_number') or bike_obj['id']}",
                                value=cur_gn,
                                key=f"log_gn_{bid}",
                                placeholder="Например, А123ВГ77",
                            )
                            gov_numbers[bid] = gn

                if st.button("Создать заявку", type="primary", key="log_create_btn"):
                    if not selected_bike_ids:
                        st.warning("Выберите хотя бы один байк.")
                    else:
                        try:
                            lid = create_logistics_request(
                                engine,
                                request_type=rtype,
                                darkstore_id=selected_ds_id,
                                bike_ids=selected_bike_ids,
                                notes=notes.strip(),
                                created_by=current_user["id"],
                            )
                            # Сохраняем гос номера для байков поставки
                            for bid, gn in gov_numbers.items():
                                if gn.strip():
                                    update_bike_gov_number(engine, bike_id=bid, gov_number=gn.strip())
                            assigned_master_name = ""
                            if selected_master != "— не назначать —":
                                assign_logistics_request(
                                    engine, logistics_id=lid,
                                    assigned_to=master_label_map[selected_master],
                                )
                                assigned_master_name = selected_master
                            bikes_in_req = [b for b in eligible if b["id"] in selected_bike_ids]
                            fake_lr = {"id": lid, "request_type": rtype,
                                       "darkstore_name": selected_ds_name, "notes": notes.strip()}
                            doc_bytes = generate_logistics_doc_bytes(
                                fake_lr, bikes_in_req,
                                darkstore_name=selected_ds_name,
                                created_by_name=full_name(current_user),
                                master_name=assigned_master_name,
                            )
                            st.session_state["log_doc_pending"] = {
                                "bytes": doc_bytes,
                                "name": logistics_doc_filename(fake_lr),
                            }
                            refresh_all_caches()
                            flash_success(f"Заявка на {rtype} создана (#{lid}). Скачайте акт выше.")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

    # --- Список активных ---
    with tab_list:
        active = [lr for lr in logistics if lr.get("status") not in ("выполнена",)]
        done = [lr for lr in logistics if lr.get("status") == "выполнена"]

        if not active:
            render_empty("Активных логистических заявок нет.")
        else:
            for lr in active:
                master_name = (
                    f"{lr.get('master_first_name') or ''} {lr.get('master_last_name') or ''}".strip()
                    or "Не назначен"
                )
                bike_count = len(lr.get("bike_ids") or [])
                render_record_card(
                    title=f"{'🔼 Поставка' if lr['request_type'] == 'поставка' else '🔽 Вывоз'} · {lr.get('darkstore_name') or '—'}",
                    subtitle=f"Мастер: {master_name} · Байков: {bike_count}",
                    status=lr.get("status") or "новая",
                    fields=[
                        ("Примечание", lr.get("notes") or "—"),
                        ("Создана", format_dt(lr.get("created_at"))),
                    ],
                )
                with st.expander(f"Действия по заявке #{lr['id']}"):
                    if lr.get("status") != "назначена":
                        master_label_map2 = {full_name(m): m["id"] for m in field_masters}
                        sel = st.selectbox(
                            "Назначить мастера",
                            list(master_label_map2.keys()),
                            key=f"log_assign_{lr['id']}",
                        )
                        if st.button("Назначить", key=f"log_assign_btn_{lr['id']}"):
                            try:
                                assign_logistics_request(engine, logistics_id=lr["id"], assigned_to=master_label_map2[sel])
                                refresh_all_caches()
                                flash_success(f"Мастер назначен на заявку #{lr['id']}.")
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))

                    # Скачать акт
                    try:
                        bike_by_id = {b["id"]: b for b in bikes}
                        if lr.get("request_type") == "замена":
                            vyvoz_bike_objs = [bike_by_id[bid] for bid in (lr.get("vyvoz_bike_ids") or []) if bid in bike_by_id]
                            post_bike_objs  = [bike_by_id[bid] for bid in (lr.get("postavka_bike_ids") or []) if bid in bike_by_id]
                            doc_bytes = generate_logistics_doc_bytes(
                                lr, [],
                                darkstore_name=lr.get("darkstore_name") or "",
                                created_by_name=full_name(current_user),
                                master_name=master_name,
                                vyvoz_bikes=vyvoz_bike_objs,
                                postavka_bikes=post_bike_objs,
                            )
                        else:
                            bikes_in_req = [bike_by_id[bid] for bid in (lr.get("bike_ids") or []) if bid in bike_by_id]
                            doc_bytes = generate_logistics_doc_bytes(
                                lr,
                                bikes_in_req,
                                darkstore_name=lr.get("darkstore_name") or "",
                                created_by_name=full_name(current_user),
                                master_name=master_name,
                            )
                        st.download_button(
                            label="📄 Скачать акт (.docx)",
                            data=doc_bytes,
                            file_name=logistics_doc_filename(lr),
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key=f"log_dl_{lr['id']}",
                        )
                    except Exception as exc:
                        st.caption(f"Документ недоступен: {exc}")

                    col_done, col_cancel = st.columns([2, 1])
                    with col_done:
                        if st.button("Отметить выполненной", key=f"log_done_{lr['id']}", type="primary"):
                            try:
                                complete_logistics_request(engine, logistics_id=lr["id"])
                                refresh_all_caches()
                                flash_success(f"Заявка #{lr['id']} выполнена, статусы байков обновлены.")
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))
                    with col_cancel:
                        if st.button("🗑 Отменить", key=f"log_cancel_{lr['id']}"):
                            try:
                                cancel_logistics_request(engine, logistics_id=lr["id"])
                                refresh_all_caches()
                                flash_success(f"Заявка #{lr['id']} отменена.")
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))

        if done:
            with st.expander(f"История выполненных ({len(done)})"):
                for lr in done[:20]:
                    bike_count = len(lr.get("bike_ids") or [])
                    st.markdown(
                        f"**#{lr['id']}** · {'Поставка' if lr['request_type'] == 'поставка' else 'Вывоз'} · "
                        f"{lr.get('darkstore_name') or '—'} · {bike_count} байк(ов) · {format_dt(lr.get('updated_at'))}"
                    )


# ---------------------------------------------------------------------------
# Импорт заявок из M4 Service Desk
# ---------------------------------------------------------------------------

def _dispatcher_m4_import(engine) -> None:
    st.markdown('<div class="section-title">Импорт заявок из M4</div>', unsafe_allow_html=True)
    st.caption(
        "Загрузите Excel-выгрузку из M4 Service Desk. "
        "Закрытые и уже импортированные заявки будут пропущены автоматически."
    )

    uploaded = st.file_uploader("Файл выгрузки M4 (.xlsx)", type=["xlsx"], key="m4_upload")

    if uploaded is not None:
        file_bytes = uploaded.read()

        # Предпросмотр
        try:
            import openpyxl
            wb = openpyxl.load_workbook(filename=__import__("io").BytesIO(file_bytes), read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if rows:
                import pandas as pd
                headers = [str(c).strip() if c is not None else "" for c in rows[0]]
                preview_data = [
                    dict(zip(headers, (str(v) if v is not None else "" for v in row)))
                    for row in rows[1:6]
                ]
                st.markdown("**Предпросмотр (первые 5 строк)**")
                st.dataframe(preview_data, use_container_width=True)
                st.caption(f"Всего строк в файле: {len(rows) - 1}")
        except Exception as exc:
            st.warning(f"Не удалось отобразить предпросмотр: {exc}")

        if st.button("Импортировать заявки", type="primary", key="m4_import_btn"):
            with st.spinner("Импортируем заявки из M4…"):
                try:
                    imported, skipped = import_m4_xlsx(engine, file_bytes)
                    flash_success(
                        f"Импорт завершён: добавлено {imported} заявок, пропущено {skipped}."
                    )
                    refresh_all_caches()
                    st.rerun()
                except Exception as exc:
                    st.error(f"Ошибка при импорте: {exc}")
