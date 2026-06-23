"""
app.py — точка входа Vanta ERP.

Содержит только: page config, main() и маршрутизатор ролей.
Вся бизнес-логика разбита по модулям:
  config.py · utils.py · db.py · ui.py
  role_curator.py · role_dispatcher.py · role_field_master.py
  role_workshop.py · role_warehouse.py
"""

import streamlit as st

from config import EMPLOYEE_ROLE_MAP, ROLE_LABELS
from db import (
    check_database_connection,
    ensure_rental_company_schema,
    get_engine,
    load_all_data,
)
from role_curator import curator_dashboard
from role_dispatcher import dispatcher_dashboard
from role_field_master import field_master_dashboard
from role_senior_workshop import senior_workshop_dashboard
from role_warehouse import warehouse_dashboard
from role_workshop import workshop_master_dashboard
from ui import inject_styles, render_flash
from utils import full_name

st.set_page_config(
    page_title="Vanta ERP",
    page_icon="🚲",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Выбор сотрудника для роли
# ---------------------------------------------------------------------------

def _choose_employee(role_key: str, employees: list[dict]) -> dict | None:
    allowed = set(EMPLOYEE_ROLE_MAP.get(role_key, ()))
    matched = [row for row in employees if row.get("role") in allowed]
    if not matched:
        return None
    options = {full_name(row): row for row in matched}
    selected = st.sidebar.selectbox("Сотрудник", list(options.keys()))
    return options[selected]


# ---------------------------------------------------------------------------
# Маршрутизатор ролей
# ---------------------------------------------------------------------------

def _render_role_screen(role_key: str, context: dict, data: dict, engine) -> None:
    if role_key == "curator":
        curator_dashboard(
            context["darkstore"],
            data["incoming_request"],
            data["bikes"],
            data["bike_logs"],
            data["rentals"],
            engine,
        )
    elif role_key == "dispatcher":
        dispatcher_dashboard(
            context["employee"],
            data["incoming_request"],
            data["repairs"],
            data["bikes"],
            data["employees"],
            data["productivity"],
            data["parts_used"],
            data["darkstores"],
            data["logistics"],
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
            data["logistics"],
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
    elif role_key == "senior_workshop":
        senior_workshop_dashboard(
            context["employee"],
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


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    inject_styles()
    render_flash()

    try:
        engine = get_engine()
    except Exception as exc:
        st.error("Не удалось создать подключение к базе данных.")
        st.code(str(exc))
        return

    if "db_connected" not in st.session_state:
        is_connected, connection_error = check_database_connection(engine)
        if not is_connected:
            st.error("База данных сейчас недоступна.")
            st.info("Соединение с Supabase pooler оборвалось до загрузки данных. Обычно это временно: попробуйте перезапустить страницу через несколько секунд.")
            if connection_error:
                st.code(connection_error)
            return
        st.session_state["db_connected"] = True

    # Все миграции уже применены — пропускаем тяжёлую проверку схемы
    st.session_state["schema_checked"] = True

    with st.spinner("Загрузка данных..."):
        try:
            data = load_all_data(engine)
        except Exception as exc:
            err = str(exc)
            st.error("Не удалось загрузить данные из базы.")
            st.warning(
                "Убедитесь что в `.streamlit/secrets.toml` порт **6543** "
                "(transaction mode), а не 5432. "
                "Если порт верный — перезапустите страницу."
            )
            st.code(err)
            if st.button("Повторить"):
                st.cache_data.clear()
                st.rerun()
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
        employee = _choose_employee(role_key, data["employees"])
        if not employee:
            st.warning("Для этой роли пока нет сотрудников в базе.")
            return
        context["employee"] = employee

    _render_role_screen(role_key, context, data, engine)


main()
