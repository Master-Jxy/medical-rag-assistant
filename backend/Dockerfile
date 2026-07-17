FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com

WORKDIR /app

RUN sed -i 's|http://archive.ubuntu.com/ubuntu/|http://mirrors.cloud.aliyuncs.com/ubuntu/|g; s|http://security.ubuntu.com/ubuntu/|http://mirrors.cloud.aliyuncs.com/ubuntu/|g' /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates python3 python3-pip && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --system app && useradd --system --gid app --home /app app

COPY backend/requirements.txt ./requirements.txt
RUN python3 -m pip install --upgrade pip setuptools wheel && \
    python3 -m pip install --timeout 120 -r requirements.txt

COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY backend/scripts ./scripts

RUN mkdir -p /app/data/uploads /app/chroma_db && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["sh", "-c", "python3 -m alembic -c alembic.ini upgrade head && exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log"]
