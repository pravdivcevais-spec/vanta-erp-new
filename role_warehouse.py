"""
role_warehouse.py — кабинет склада.
"""

from datetime import datetime, date

import streamlit as st

from db import (
    adjust_stock,
    create_company,
    create_private_client,
    finish_rental,
    issue_b2b_rental,
    issue_b2c_rental,
    refresh_all_caches,
    report_rental_theft,
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
    filter_bikes,
    format_dt,
    format_short_date,
    full_name,
)


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
        _warehouse_bikes(bikes)
    elif section == "Аренда":
        _warehouse_rental(
            darkstores, clients, companies, rentals,
            free_serviceable_bikes, private_clients, active_rentals,
            bike_label, client_label, company_label, darkstore_label_local, rental_days,
            engine,
        )
    else:
        _warehouse_parts(stock, spare_catalog, darkstores, master_stock, darkstore_label_local, engine)


# ---------------------------------------------------------------------------

def _warehouse_bikes(bikes):
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


def _warehouse_rental(
    darkstores, clients, companies, rentals,
    free_serviceable_bikes, private_clients, active_rentals,
    bike_label, client_label, company_label, darkstore_label_local, rental_days,
    engine,
):
    st.markdown('<div class="section-title">Аренда</div>', unsafe_allow_html=True)
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


def _warehouse_parts(stock, spare_catalog, darkstores, master_stock, darkstore_label_local, engine):
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
