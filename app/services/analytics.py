"""投稿後分析(要件12章・追補6章)。指標を取得区分ごとに分類して扱う。

- auto : YouTube Analytics APIで自動取得
- studio: YouTube Studioで人間が確認(API未提供・要目視)
- proxy : 直接取得不可。代替指標で評価
- calc : 本システムの記録から算出
推測値での補完は行わない(追補6章)。
"""

from __future__ import annotations

from app.config import settings
from app.models import Project

METRICS: list[tuple[str, str, str]] = [
    ("views", "視聴回数", "auto"),
    ("estimatedMinutesWatched", "総再生時間(分)", "auto"),
    ("averageViewDuration", "平均視聴時間(秒)", "auto"),
    ("averageViewPercentage", "平均視聴率(%)", "auto"),
    ("likes", "高評価数", "auto"),
    ("comments", "コメント数", "auto"),
    ("subscribersGained", "登録者増", "auto"),
    ("subscribersLost", "登録者減", "auto"),
    ("impressions", "インプレッション(表示回数)", "studio"),
    ("ctr", "インプレッションのクリック率", "studio"),
    ("retention", "視聴者維持率・離脱位置", "studio"),
    ("shorts_to_long", "Shortsから通常動画への流入", "proxy"),
    ("cost_perf", "制作費に対する成果", "calc"),
]

CATEGORY_LABEL = {
    "auto": "自動取得", "studio": "YouTube Studioで確認",
    "proxy": "代替指標で評価", "calc": "本システムで算出",
}


def fetch(project: Project) -> dict:
    video_id = project.publish_info.youtube_video_id
    values: dict[str, object] = {}
    note = ""
    if settings.is_local or not video_id or video_id.startswith("LOCAL-"):
        note = "ローカルモードまたは未投稿のため実測値なし(推測値では補完しない)"
    else:
        try:
            values = _fetch_youtube_analytics(video_id)
        except Exception as e:  # 分析失敗は案件を止めない
            note = f"取得エラー: {e}"
    values["cost_perf"] = f"制作費 ¥{project.total_cost()}" + (
        f" / 視聴 {values['views']}回" if values.get("views") else " (視聴データ未取得)")
    return {"metrics": METRICS, "values": values, "note": note,
            "category_label": CATEGORY_LABEL}


def _fetch_youtube_analytics(video_id: str) -> dict:
    """クラウドモード: 投稿サービス経由でYouTube Analytics値を取得する。"""
    import requests
    from google.auth.transport.requests import Request as AuthRequest
    from google.oauth2 import id_token as google_id_token

    token = google_id_token.fetch_id_token(AuthRequest(), settings.uploader_url)
    resp = requests.get(
        f"{settings.uploader_url}/analytics/{video_id}",
        headers={"Authorization": f"Bearer {token}"}, timeout=60,
    )
    resp.raise_for_status()
    return resp.json()
