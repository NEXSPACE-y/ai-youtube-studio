# 投稿サービス(YouTube権限を持つ唯一のサービス。生成処理から分離: 要件9章)
FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" pydantic \
    google-cloud-firestore google-cloud-storage \
    google-api-python-client google-auth google-auth-oauthlib

COPY app ./app
COPY uploader ./uploader

CMD ["sh", "-c", "uvicorn uploader.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
