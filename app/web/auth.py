"""アクセス制御。ローカル=固定ユーザー / クラウド=IAPのヘッダ検証。"""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.config import settings


def current_user(request: Request) -> str:
    if settings.is_local:
        return "豆虎(local)"
    email = request.headers.get("x-goog-authenticated-user-email", "")
    email = email.split(":", 1)[-1]  # "accounts.google.com:foo@bar" 形式
    if not email:
        raise HTTPException(status_code=401, detail="IAP経由でアクセスしてください")
    if settings.allowed_emails and email not in settings.allowed_emails:
        raise HTTPException(status_code=403, detail=f"{email} は許可されていません")
    return email
