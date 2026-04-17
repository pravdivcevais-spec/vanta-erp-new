import streamlit as st
from sqlalchemy import create_engine, text

# Прямое создание движка с параметрами для облака
engine = create_engine(
    st.secrets["DATABASE_URL"],
    connect_args={
        "connect_timeout": 10,
        "application_name": "vanta_erp",
        "options": "-c prepare_threshold=0"  # Вот теперь это уйдет правильно
    },
    pool_pre_ping=True
)

st.title("📱 Кабинет выездного мастера")

# ID мастера (пока хардкод для теста)
MASTER_ID = 1 

try:
    with engine.connect() as conn:
        # Простой запрос для проверки связи
        query = text("""
            SELECT rr.id, b.serial_number, rr.status
            FROM repair_request rr
            JOIN bike b ON rr.bike_id = b.id
            WHERE rr.master_id = :mid AND rr.status IN ('назначена', 'в работе')
        """)
        tasks = conn.execute(query, {"mid": MASTER_ID}).fetchall()

    if not tasks:
        st.info("Активных заявок нет")
    else:
        for task in tasks:
            with st.container(border=True):
                st.write(f"**Заявка №{task.id}** | Байк: {task.serial_number}")
                st.write(f"Статус: {task.status}")
                
                # Кнопка для теста связи
                if st.button(f"Обновить {task.id}", key=task.id):
                    st.success("Связь есть!")

except Exception as e:
    st.error("Ошибка подключения к базе")
    st.code(str(e))
