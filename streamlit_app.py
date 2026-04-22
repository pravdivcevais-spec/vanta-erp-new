import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


PAGE_TITLE = "Кабинет мастера"
PAGE_ICON = "📱"
ACTIVE_STATUSES = {"назначена", "в работе"}

st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON)
st.title(f"{PAGE_ICON} Кабинет выездного мастера")


def normalize_supabase_database_url(raw_url: str, project_ref: str | None) -> str:
    url = make_url(raw_url)
    host = url.host or ""
    username = url.username or ""

    if host.endswith("pooler.supabase.com"):
        if "." not in username:
            if not project_ref:
                raise ValueError(
                    "Для Supabase pooler нужен SUPABASE_PROJECT_REF "
                    "или логин вида postgres.<project_ref> в DATABASE_URL."
                )
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
        connect_args={
            "connect_timeout": 10,
            "sslmode": "require",
        },
    )


def verify_connection_twice(engine) -> None:
    for _ in range(2):
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))


def load_tasks(engine, master_id: int):
    with engine.connect() as conn:
        query = text(
            """
            SELECT
                rr.id,
                b.serial_number,
                rr.status,
                ma.assigned_at,
                ma.comment
            FROM repair_request rr
            JOIN master_assignment ma ON ma.repair_request_id = rr.id
            JOIN bike b ON rr.bike_id = b.id
            WHERE ma.assigned_to = :mid
            ORDER BY rr.id
            """
        )
        rows = conn.execute(query, {"mid": master_id}).fetchall()

    return [row for row in rows if row.status in ACTIVE_STATUSES]


default_master_id = int(st.secrets.get("MASTER_ID", 1))
master_id = st.sidebar.number_input(
    "Идентификатор мастера",
    min_value=1,
    value=default_master_id,
    step=1,
)
st.sidebar.caption(
    "По умолчанию берется MASTER_ID из secrets, но его можно изменить в боковой панели."
)

try:
    engine = get_engine()
    verify_connection_twice(engine)
    st.caption("Подключение к базе успешно проверено 2 раза.")

    tasks = load_tasks(engine, int(master_id))

    if not tasks:
        st.info("Активных заявок нет")
    else:
        for task in tasks:
            with st.container(border=True):
                st.write(f"**Заявка №{task.id}** | Байк: {task.serial_number}")
                st.write(f"Статус: {task.status}")
                if task.assigned_at:
                    st.write(f"Назначена: {task.assigned_at:%d.%m.%Y %H:%M}")
                if task.comment:
                    st.write(f"Комментарий: {task.comment}")

                if st.button(f"Обновить статус {task.id}", key=f"btn_{task.id}"):
                    st.success(f"Заявка {task.id} обновлена")

except Exception as e:
    err_msg = str(e)
    st.error("Ошибка подключения к базе")

    if "Tenant or user not found" in err_msg:
        st.warning(
            "Supabase не принял пользователя из DATABASE_URL. "
            "Для pooler-хоста нужен логин вида postgres.<project_ref>."
        )

    st.code(err_msg)
    st.info(
        "Проверьте Secrets: DATABASE_URL, SUPABASE_PROJECT_REF, MASTER_ID, пароль и host Supabase."
    )
