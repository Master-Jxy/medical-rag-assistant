FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home /app app

COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt

COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY backend/scripts ./scripts

RUN mkdir -p /app/data/uploads /app/chroma_db && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["sh", "-c", "python -m alembic -c alembic.ini upgrade head && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log"]

