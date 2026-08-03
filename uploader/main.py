"""投稿サービス(要件9章: 公開操作を生成処理から分離)。

- Cloud Runに `--no-allow-unauthenticated` でデプロイし、呼び出しは
  管理アプリのサービスアカウントのみIAMで許可する。
- /publish はFirestore上の公開承認レコードをサーバ側で再検証してからのみ実行。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent))  # app.models を共用

from app.models import Project  # noqa: E402
from uploader import youtube_client  # noqa: E402

GCP_PROJECT = os.getenv("GCP_PROJECT", "")
GCS_BUCKET = os.getenv("GCS_BUCKET", "")

app = FastAPI(title="AI YouTube Studio Uploader")

# 公開承認チェックリスト(app/services/approval.py と同一キー)
PUBLISH_CHECKLIST_KEYS = [
    "accuracy", "consistency", "quality", "rights", "real_entities",
    "ai_disclosure", "policy", "no_clickbait", "uniqueness",
]


def _load_project(project_id: str) -> Project:
    from google.cloud import firestore

    doc = firestore.Client(project=GCP_PROJECT).collection("projects") \
        .document(project_id).get()
    if not doc.exists:
        raise HTTPException(404, "案件が見つかりません")
    return Project.model_validate(doc.to_dict())


def _save_video_id(project_id: str, video_id: str) -> None:
    from google.cloud import firestore

    firestore.Client(project=GCP_PROJECT).collection("projects") \
        .document(project_id).update({"publish_info.youtube_video_id": video_id})


def _read_gcs(name: str) -> bytes:
    from google.cloud import storage

    return storage.Client(project=GCP_PROJECT).bucket(GCS_BUCKET) \
        .blob(name).download_as_bytes()


def _verify_publish_approval(project: Project) -> None:
    """承認レコードなしに公開しない(要件5.8)。UIとは独立にここでも検証する。"""
    for a in project.approvals:
        if (a.stage == "公開承認" and a.decision == "approved"
                and all(a.checklist.get(k) for k in PUBLISH_CHECKLIST_KEYS)):
            return
    raise HTTPException(403, "有効な公開承認レコードがありません。公開は拒否されました")


class ProjectRef(BaseModel):
    project_id: str


@app.post("/upload")
def upload(ref: ProjectRef):
    """非公開アップロード。承認前でも実行可(公開はしない)。"""
    project = _load_project(ref.project_id)
    render = next((a for a in reversed(project.assets)
                   if a.kind == "render" and a.adopted
                   and a.meta.get("format") == "mp4"), None)
    if render is None:
        raise HTTPException(400, "完成動画(mp4)がありません")
    pi = project.publish_info
    video_id = youtube_client.upload_private(
        _read_gcs(render.path), pi.title or project.title, pi.description,
        pi.tags, pi.ai_disclosure)
    thumb = next((a for a in reversed(project.assets)
                  if a.kind == "thumbnail" and a.adopted), None)
    if thumb:
        youtube_client.set_thumbnail(video_id, _read_gcs(thumb.path))
    _save_video_id(ref.project_id, video_id)
    return {"video_id": video_id, "privacy": "private"}


@app.post("/publish")
def publish(ref: ProjectRef):
    """公開承認レコードを検証してから公開する。"""
    project = _load_project(ref.project_id)
    _verify_publish_approval(project)
    video_id = project.publish_info.youtube_video_id
    if not video_id:
        result = upload(ref)
        video_id = result["video_id"]
    youtube_client.set_public(video_id)
    return {"video_id": video_id, "privacy": "public"}


@app.get("/analytics/{video_id}")
def get_analytics(video_id: str):
    return youtube_client.analytics(video_id)


@app.get("/healthz")
def healthz():
    return {"ok": True}
