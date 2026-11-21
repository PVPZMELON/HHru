# Публикация HHru Market Analytics

## Состав
- Backend: FastAPI, Python 3.12, Docker, Render.
- Frontend: React + TypeScript + Vite, Vercel.
- Database: PostgreSQL (подойдёт существующая база Neon).
- Источник: официальный API hh.ru.

## 1. Подготовить PostgreSQL (Neon)
1. Откройте проект Neon и скопируйте параметры подключения к PostgreSQL.
2. Не публикуйте строку подключения, пароль и токен hh.ru в GitHub или чате.
3. Для Render потребуются отдельные значения: host, port, database, user, password. Для TLS используйте `DB_SSLMODE=require`.
4. При первом старте backend выполнит миграции автоматически.

## 2. Развернуть backend на Render
1. Создайте Web Service из GitHub-репозитория.
2. Выберите ветку `ci-backend-frontend` для первого тестового деплоя. Не переключайте production на неё до проверки.
3. Render должен использовать Blueprint `render.yaml` из корня репозитория.
4. В Environment добавьте значения `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_SSLMODE=require`, `HH_API_TOKEN`.
5. Сгенерируйте отдельный длинный случайный `ADMIN_API_TOKEN` и сохраните в менеджере паролей. Он не должен совпадать с токеном hh.ru.
6. После успешного deploy проверьте `https://<backend-host>/api/v1/health`, затем `/api/v1/ready` и `/api/docs`.

## 3. Развернуть frontend на Vercel
1. Импортируйте тот же GitHub-репозиторий в Vercel.
2. Укажите Root Directory: `hh-bigdata/frontend`.
3. Build Command: `npm run build`; Output Directory: `dist`; Install Command: `npm install`.
4. Добавьте переменную окружения `VITE_API_BASE_URL=https://<backend-host>` (без завершающего слеша).
5. Добавьте домен frontend в `FRONTEND_ORIGINS` backend-сервиса, например `https://<project>.vercel.app`.
6. Повторно разверните backend после изменения `FRONTEND_ORIGINS`, затем frontend.

## 4. Проверить сбор данных
- Откройте сайт и проверьте статус API, обзор, каталог и страницы аналитики.
- Чтобы запустить сбор из защищённого API, отправьте POST на `/api/v1/etl/collect` с заголовком `X-Admin-Token: <ADMIN_API_TOKEN>`. Не встраивайте этот токен в frontend, JavaScript, публичные переменные Vercel или Git.
- Ответ содержит номер запуска и счётчики ETL. Страница «Качество данных» показывает историю и состояние таблиц.
- Если hh.ru отвечает 401/403, не пытайтесь обходить защиту: проверьте права токена и используйте предусмотренный импорт файлов.

## 5. Локальный запуск
Backend из каталога `hh-bigdata`:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m src.pipeline migrate
uvicorn backend.app.main:app --reload
```

Frontend из `hh-bigdata/frontend`:
```bash
npm install
cp .env.example .env.local
npm run dev
```

Для локального frontend задайте `VITE_API_BASE_URL=http://127.0.0.1:8000`. В Windows используйте активацию окружения `.venv\\Scripts\\activate`.

## Важно
- Сначала проверяйте ветку и preview deployment; не переносите её в production, пока CI и ручная проверка не зелёные.
- В репозитории нет рабочих production-секретов. Их владелец вводит только в защищённых настройках Render/Neon/Vercel.
- Публичный health endpoint проверяет процесс; ready endpoint дополнительно проверяет базу.
- Для бесплатных тарифов Render сервис может засыпать; первый запрос после простоя может выполняться дольше.
