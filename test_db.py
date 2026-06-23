import psycopg2

url = "postgresql://postgres.dnddozgfojhanlybqewf:VantaBikes123@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"

print("Пробуем подключиться...")
try:
    conn = psycopg2.connect(url, connect_timeout=15, sslmode="require")
    cur = conn.cursor()
    cur.execute("SELECT 1")
    print("✅ Подключение работает!")
    conn.close()
except Exception as e:
    print(f"❌ Ошибка: {e}")

print("Пробуем без SSL...")
try:
    conn = psycopg2.connect(url, connect_timeout=15, sslmode="prefer")
    cur = conn.cursor()
    cur.execute("SELECT 1")
    print("✅ Без SSL работает!")
    conn.close()
except Exception as e:
    print(f"❌ Ошибка: {e}")
