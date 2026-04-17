import streamlit as st
from sqlalchemy import create_engine, text

# 1. Подключение к базе (данные возьмем из настроек Streamlit позже)
def get_conn():
    db_url = st.secrets["DATABASE_URL"]
    return create_engine(db_url)

engine = get_conn()

st.title("📱 Кабинет выездного мастера")

# В MVP эмулируем, что зашел мастер с ID 1
MASTER_ID = 1 

# 2. Получаем список назначенных заявок
query = text("""
    SELECT rr.id, rr.bike_id, b.serial_number, rr.status, rr.type
    FROM repair_request rr
    JOIN bike b ON rr.bike_id = b.id
    WHERE rr.master_id = :master_id 
      AND rr.status IN ('назначена', 'в работе')
""")

with engine.connect() as conn:
    tasks = conn.execute(query, {"master_id": MASTER_ID}).fetchall()

if not tasks:
    st.info("У вас нет активных заявок на ремонт")
else:
    for task in tasks:
        with st.container(border=True):
            st.write(f"**Заявка №{task.id}** | Байк: {task.serial_number}")
            st.write(f"Тип: {task.type} | Статус: {task.status}")

            # ЛОГИКА КНОПОК
            if task.status == 'назначена':
                if st.button(f"Начать ремонт {task.id}", key=f"start_{task.id}"):
                    with engine.begin() as conn:
                        # Меняем статус заявки
                        conn.execute(text("UPDATE repair_request SET status = 'в работе' WHERE id = :id"), {"id": task.id})
                        # Меняем статус байка
                        conn.execute(text("UPDATE bike SET tech_status = 'В ремонте' WHERE id = :id"), {"id": task.bike_id})
                        # Пишем в лог
                        conn.execute(text("""
                            INSERT INTO bike_log (bike_id, employee_id, new_tech_status, description)
                            VALUES (:b_id, :e_id, 'В ремонте', 'Мастер начал работу')
                        """), {"b_id": task.bike_id, "e_id": MASTER_ID})
                    st.rerun()

            if task.status == 'в работе':
                if st.button(f"✅ Завершить ремонт {task.id}", key=f"comp_{task.id}"):
                    with engine.begin() as conn:
                        conn.execute(text("UPDATE repair_request SET status = 'завершена' WHERE id = :id"), {"id": task.id})
                        conn.execute(text("UPDATE bike SET tech_status = 'Исправен' WHERE id = :id"), {"id": task.bike_id})
                        conn.execute(text("""
                            INSERT INTO bike_log (bike_id, employee_id, new_tech_status, description)
                            VALUES (:b_id, :e_id, 'Исправен', 'Ремонт завершен успешно')
                        """), {"b_id": task.bike_id, "e_id": MASTER_ID})
                    st.success("Готово!")
                    st.rerun()
