# Публикация на Streamlit Community Cloud

Streamlit Cloud запускает только приложение; **PostgreSQL там нет** — нужна внешняя БД (бесплатные: Neon, Supabase).

1. **Зависимости.** Cloud ищет `requirements.txt` в корне репозитория (или рядом с главным файлом). Положите содержимое
   `requirements-cloud.txt` в `requirements.txt` в **корне репозитория** (если проект лежит в подпапке `hh-bigdata/`,
   файл нужен и там, и в корне — достаточно корня).
2. **БД.** Создайте базу в Neon/Supabase, возьмите host, port, dbname, user, password.
3. **Secrets** (App → Settings → Secrets), формат TOML:
   ```toml
   DB_HOST = "..."
   DB_PORT = "5432"
   DB_NAME = "..."
   DB_USER = "..."
   DB_PASSWORD = "..."
   DB_SSLMODE = "require"
   ```
4. **Схема и данные** создавайте с компьютера, указав те же значения в локальном `.env`:
   `python -m src.pipeline migrate`, затем `python -m src.pipeline demo` (или `collect`).
5. Main file path: `hh-bigdata/src/dashboard/app.py` (или `src/dashboard/app.py`, если проект в корне).
6. Python 3.14 на Cloud может не иметь колёс для части пакетов; при ошибке установки в Advanced settings выберите Python 3.12 или 3.13.
