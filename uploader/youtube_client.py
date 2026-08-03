"""YouTube Data / Analytics APIクライアント(投稿サービス専用)。

認証情報は環境変数(Secret Manager経由)でのみ受け取る(要件9章)。
"""

from __future__ import annotations

import os
import tempfile


def _credentials():
    from google.oauth2.credentials import Credentials

    return Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )


def _service(name: str, version: str):
    from googleapiclient.discovery import build

    return build(name, version, credentials=_credentials(), cache_discovery=False)


def upload_private(video_bytes: bytes, title: str, description: str,
                   tags: list[str], ai_disclosure: bool) -> str:
    """非公開でアップロードし video_id を返す(要件4章: 初回公開状態は非公開)。"""
    from googleapiclient.http import MediaFileUpload

    yt = _service("youtube", "v3")
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(video_bytes)
        path = f.name
    try:
        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:4900],
                "tags": tags[:30],
                "categoryId": "27",  # Education
            },
            "status": {
                "privacyStatus": "private",
                "selfDeclaredMadeForKids": False,
                # AI生成コンテンツの申告(要件11章)
                "containsSyntheticMedia": ai_disclosure,
            },
        }
        media = MediaFileUpload(path, mimetype="video/mp4", resumable=True)
        req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
        resp = None
        while resp is None:
            _, resp = req.next_chunk()
        return resp["id"]
    finally:
        os.unlink(path)


def set_public(video_id: str) -> None:
    yt = _service("youtube", "v3")
    yt.videos().update(
        part="status",
        body={"id": video_id,
              "status": {"privacyStatus": "public",
                         "selfDeclaredMadeForKids": False}},
    ).execute()


def set_thumbnail(video_id: str, image_bytes: bytes) -> None:
    from googleapiclient.http import MediaInMemoryUpload

    yt = _service("youtube", "v3")
    yt.thumbnails().set(
        videoId=video_id,
        media_body=MediaInMemoryUpload(image_bytes, mimetype="image/png"),
    ).execute()


def analytics(video_id: str) -> dict:
    ya = _service("youtubeAnalytics", "v2")
    resp = ya.reports().query(
        ids="channel==MINE",
        startDate="2020-01-01", endDate="2100-01-01",
        metrics=("views,estimatedMinutesWatched,averageViewDuration,"
                 "averageViewPercentage,likes,comments,subscribersGained,subscribersLost"),
        filters=f"video=={video_id}",
    ).execute()
    headers = [h["name"] for h in resp.get("columnHeaders", [])]
    rows = resp.get("rows", [[]])
    return dict(zip(headers, rows[0])) if rows and rows[0] else {}
