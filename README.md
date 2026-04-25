# Vanta ERP 1.0

Streamlit-приложение для кабинета выездного мастера с подключением к Supabase Postgres.

## Файлы проекта

- `app.py` — основное Streamlit-приложение
- `requirements.txt` — зависимости для локального запуска и Streamlit Cloud
- `.streamlit/secrets.toml.example` — шаблон секретов
- `.gitignore` — исключает реальные секреты из Git

## 1. Локальный запуск

1. Откройте PowerShell.
2. Перейдите в папку проекта:

```powershell
cd "C:\Users\iprav\OneDrive\Рабочий стол\Vanta ERP 1.0"
```

3. Установите зависимости:

```powershell
python -m pip install -r requirements.txt
```

4. Создайте файл `.streamlit/secrets.toml`.
5. Вставьте в него рабочие секреты:

```toml
DATABASE_URL = "postgresql://postgres.dnddozgfojhanlybqewf:YOUR_DB_PASSWORD@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
SUPABASE_PROJECT_REF = "dnddozgfojhanlybqewf"
MASTER_ID = 1
```

6. Запустите приложение:

```powershell
python -m streamlit run app.py
```

## 2. Загрузка в GitHub

1. Создайте пустой репозиторий на GitHub.
2. В PowerShell выполните:

```powershell
cd "C:\Users\iprav\OneDrive\Рабочий стол\Vanta ERP 1.0"
git init
git add app.py requirements.txt .gitignore README.md .streamlit/secrets.toml.example
git commit -m "Add Streamlit master dashboard"
git branch -M main
git remote add origin YOUR_GITHUB_REPOSITORY_URL
git push -u origin main
```

3. Убедитесь, что `.streamlit/secrets.toml` не попал в репозиторий.

## 3. Запуск в Streamlit Cloud

1. Зайдите в [Streamlit Community Cloud](https://share.streamlit.io/).
2. Нажмите `New app`.
3. Выберите ваш GitHub-репозиторий.
4. Укажите:
- Branch: `main`
- Main file path: `app.py`
5. Откройте раздел `Advanced settings` или `Secrets`.
6. Вставьте туда секреты:

```toml
DATABASE_URL = "postgresql://postgres.dnddozgfojhanlybqewf:YOUR_DB_PASSWORD@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
SUPABASE_PROJECT_REF = "dnddozgfojhanlybqewf"
MASTER_ID = 1
```

7. Нажмите Deploy.

## 4. Что уже проверено

- Подключение к Supabase Session Pooler прошло успешно 2 раза подряд.
- Схема таблиц проверена на живой базе.
- Приложение читает заявки через `master_assignment`, а не через отсутствующий `repair_request.master_id`.
- Для мастера `1` в базе находятся активные заявки со статусами `назначена` и `в работе`.

## 5. Важное

- Не публикуйте `.streamlit/secrets.toml` в GitHub.
- После завершения настройки смените пароль базы, если он уже был отправлен в переписке.
