"""人間承認(要件5.8・13章)。承認記録なしに公開されない構造の中核。"""

from __future__ import annotations

from app import states
from app.config import settings
from app.models import ApprovalRecord, Project
from app.services import publish_prep

QUALITY_CHECKLIST: list[tuple[str, str]] = [
    ("video_ok", "映像に著しい破綻・不自然な生成物がない(要件6.2)"),
    ("audio_ok", "読み間違い・不自然な無音・音量差・音声切断がない(要件6.3)"),
    ("subs_ok", "字幕の内容とタイミングが正しい(追補7章)"),
    ("script_match", "台本と完成動画の内容が整合している"),
    ("bgm_ok", "BGMがナレーションを妨げていない"),
]

PUBLISH_CHECKLIST: list[tuple[str, str]] = [
    ("accuracy", "内容の正確性を情報源と照合した"),
    ("consistency", "台本と完成動画の整合性を確認した"),
    ("quality", "音声・字幕・映像の品質を確認した"),
    ("rights", "著作権および素材の利用条件を確認した"),
    ("real_entities", "実在の人物・企業・事件に関する表現に問題がない"),
    ("ai_disclosure", "AI生成コンテンツの申告要否を確認した"),
    ("policy", "YouTube規約・収益化ポリシーに適合している"),
    ("no_clickbait", "タイトル・サムネイルに過剰表現がない"),
    ("uniqueness", "この動画の独自要素を説明できる(要件6.4)"),
]


class ApprovalError(Exception):
    pass


def approve_script(project: Project, actor: str, note: str = "") -> None:
    project.approvals.append(ApprovalRecord(
        stage="台本確認", decision="approved", approver=actor, reason=note))
    states.transition(project, states.ASSETS, actor=actor, note="台本承認")


def reject_script(project: Project, actor: str, reason: str) -> None:
    project.approvals.append(ApprovalRecord(
        stage="台本確認", decision="rejected", approver=actor, reason=reason,
        rollback_to=states.SCRIPTING))
    states.rollback(project, states.SCRIPTING, reason=reason, actor=actor)


def submit_quality(project: Project, actor: str, checklist: dict[str, bool],
                   ok: bool, reason: str = "", rollback_to: str = "") -> None:
    if ok:
        missing = [label for key, label in QUALITY_CHECKLIST if not checklist.get(key)]
        if missing:
            raise ApprovalError("未確認の項目があります: " + " / ".join(missing))
        project.approvals.append(ApprovalRecord(
            stage="品質確認", decision="approved", approver=actor, checklist=checklist))
        states.transition(project, states.APPROVAL, actor=actor, note="品質確認合格")
        publish_prep.run(project)
    else:
        if not reason.strip():
            raise ApprovalError("差し戻し理由は必須です")
        project.approvals.append(ApprovalRecord(
            stage="品質確認", decision="rejected", approver=actor, reason=reason,
            checklist=checklist, rollback_to=rollback_to or states.EDITING))
        states.rollback(project, rollback_to or states.EDITING, reason=reason, actor=actor)


def submit_publish(project: Project, actor: str, checklist: dict[str, bool],
                   decision: str, reason: str = "", rollback_to: str = "") -> None:
    """公開承認(豆虎Gate)。承認記録を残してからのみ公開処理へ進む。"""
    if decision == "approved":
        missing = [label for key, label in PUBLISH_CHECKLIST if not checklist.get(key)]
        if missing:
            raise ApprovalError("未確認の項目があります: " + " / ".join(missing))
        project.approvals.append(ApprovalRecord(
            stage="公開承認", decision="approved", approver=actor, checklist=checklist))
        _publish(project)
        states.transition(project, states.PUBLISHED, actor=actor, note="豆虎Gate承認・公開")
    else:
        if not reason.strip():
            raise ApprovalError("差し戻し理由は必須です")
        project.approvals.append(ApprovalRecord(
            stage="公開承認", decision="rejected", approver=actor, reason=reason,
            checklist=checklist, rollback_to=rollback_to or states.QA))
        states.rollback(project, rollback_to or states.QA, reason=reason, actor=actor)


def has_publish_approval(project: Project) -> bool:
    """投稿サービス側でも検証する公開可否判定(要件9章: 誤公開防止)。"""
    return any(
        a.stage == "公開承認" and a.decision == "approved"
        and all(a.checklist.get(k) for k, _ in PUBLISH_CHECKLIST)
        for a in project.approvals
    )


def _publish(project: Project) -> None:
    if settings.is_local or not settings.uploader_url:
        project.publish_info.youtube_video_id = f"LOCAL-{project.id}"
        project.log("公開処理(ローカルモードのため実投稿なし)")
        return
    import requests
    from google.auth.transport.requests import Request as AuthRequest
    from google.oauth2 import id_token as google_id_token

    token = google_id_token.fetch_id_token(AuthRequest(), settings.uploader_url)
    resp = requests.post(
        f"{settings.uploader_url}/publish",
        json={"project_id": project.id},
        headers={"Authorization": f"Bearer {token}"}, timeout=600,
    )
    resp.raise_for_status()
    project.publish_info.youtube_video_id = resp.json().get("video_id", "")
    project.log("YouTube公開処理を実行", note=project.publish_info.youtube_video_id)
