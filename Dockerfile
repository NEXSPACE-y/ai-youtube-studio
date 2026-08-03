# 管理・承認Webアプリ + 生成パイプライン(Cloud Run)
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV APP_MODE=cloud
CMD ["sh", "-c", "uvicorn app.web.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
