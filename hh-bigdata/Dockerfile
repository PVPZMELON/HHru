FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/hh-bigdata
WORKDIR /app/hh-bigdata
COPY hh-bigdata/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY hh-bigdata/src ./src
COPY hh-bigdata/backend ./backend
COPY hh-bigdata/migrations ./migrations
EXPOSE 8000
CMD ["sh", "-c", "python -m src.pipeline migrate && uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
