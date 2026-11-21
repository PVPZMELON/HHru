# Frontend (первый этап)

React + TypeScript + Vite. Сейчас это самостоятельный UI-каркас с дизайн-направлением Editorial / lime graphite. Данные аналитики пока не подключены; единственный запрос — liveness check backend.

## Запуск

Из каталога `hh-bigdata/frontend/`:

```bash
npm install
cp .env.example .env
npm run dev
```

Откройте адрес, который напечатает Vite (обычно http://127.0.0.1:5173).

Backend запускается отдельно из `hh-bigdata/`:

```bash
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Если frontend и backend работают на разных origins, задайте backend-переменную `FRONTEND_ORIGINS=http://127.0.0.1:5173`.

## Переменные

- `VITE_API_BASE_URL` — публичный адрес backend API. Здесь нельзя хранить пароли, DB URL или токен hh.ru: все переменные с префиксом `VITE_` доступны браузеру.

## Текущее ограничение

Навигационные пункты и карточки пока являются визуальным каркасом. Они не выдают аналитические данные и не заменяют существующий Streamlit dashboard.
