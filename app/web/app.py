"""管理・承認Webアプリ(FastAPI)。承認作業を一か所で完結させる(追補4章)。"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import states
from app.costs import CostLimitExceeded
from app.llm import LLMError
from app.services.motion import has_display as motion_has
from app.models import Project
from app.repo import get_repo
from app.services import (analytics, approval, display, media, planning,
                          publish_prep, render, research, scripting, storyboard)
from app.storage import get_storage
from app.web.auth import current_user

BASE = Path(__file__).parent
app = FastAPI(title="AI YouTube Studio")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.globals.update(states=states, approval=approval)


def _jst(ts: str) -> str:
    """ISO文字列(UTC)を日本時間の 'YYYY-MM-DD HH:MM' に変換して表示する。"""
    from datetime import datetime, timedelta, timezone

    try:
        dt = datetime.fromisoformat(ts)
        return dt.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return ts


templates.env.filters["jst"] = _jst


def _back(project_id: str, msg: str = "") -> RedirectResponse:
    url = f"/projects/{project_id}"
    if msg:
        url += f"?msg={quote(msg)}"
    return RedirectResponse(url, status_code=303)


def _load(project_id: str) -> Project:
    project = get_repo().get(project_id)
    if project is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="案件が見つかりません")
    return project


def _checklist_from(form: dict, items: list[tuple[str, str]]) -> dict[str, bool]:
    return {key: form.get(f"chk_{key}") == "on" for key, _ in items}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, user: str = Depends(current_user)):
    projects = get_repo().list_all()
    return templates.TemplateResponse(request, "dashboard.html", {
        "projects": projects, "user": user, "msg": request.query_params.get("msg", ""),
    })


@app.post("/projects")
def create_project(request: Request, theme: str = Form(...),
                   user: str = Depends(current_user)):
    repo = get_repo()
    existing = [p.title for p in repo.list_all()]
    project = planning.make_project(theme.strip(), existing)
    repo.save(project)
    return _back(project.id, "企画案を生成しました")


def _metrics(project: Project) -> dict:
    """初期検証の計測(要件14章): 所要時間・費用・再生成回数を算出する。"""
    from datetime import datetime

    by_service: dict[str, float] = {}
    for c in project.costs:
        by_service[c.service] = round(by_service.get(c.service, 0) + c.cost_jpy, 1)
    rejected = sum(1 for a in project.assets if not a.adopted)
    regen = sum(1 for a in project.assets if a.version > 1)
    elapsed_h = ""
    try:
        t0 = datetime.fromisoformat(project.created_at)
        t1 = datetime.fromisoformat(project.updated_at)
        elapsed_h = f"{(t1 - t0).total_seconds() / 3600:.1f}"
    except ValueError:
        pass
    return {
        "total": project.total_cost(), "by_service": by_service,
        "rejected_assets": rejected, "regenerated": regen,
        "veo_seconds": sum(c.quantity for c in project.costs
                           if c.service == "veo_second"),
        "elapsed_hours": elapsed_h,
        "approvals": len(project.approvals),
        "rollbacks": len(project.rollbacks),
    }


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail(project_id: str, request: Request,
                   user: str = Depends(current_user)):
    project = _load(project_id)
    storage = get_storage()
    render_asset = media.find_asset(project, "editing", None, "render")
    return templates.TemplateResponse(request, "project.html", {
        "p": project, "user": user, "storage": storage,
        "render_asset": render_asset, "find_asset": media.find_asset,
        "metrics": _metrics(project),
        "msg": request.query_params.get("msg", ""),
    })


@app.post("/projects/{project_id}/title")
def set_title(project_id: str, title: str = Form(...),
              user: str = Depends(current_user)):
    project = _load(project_id)
    project.title = title
    project.log("タイトルを変更", actor=user, note=title)
    get_repo().save(project)
    return _back(project_id, "タイトルを設定しました")


@app.post("/projects/{project_id}/decide")
def decide(project_id: str, decision: str = Form(...),
           user: str = Depends(current_user)):
    project = _load(project_id)
    try:
        planning.decide(project, decision, user)
    except (states.StateError, ValueError) as e:
        return _back(project_id, str(e))
    get_repo().save(project)
    return _back(project_id, f"企画を{decision}にしました")


@app.post("/projects/{project_id}/research")
def run_research(project_id: str, user: str = Depends(current_user)):
    project = _load(project_id)
    try:
        research.run(project)
    except (CostLimitExceeded, LLMError) as e:
        get_repo().save(project)
        return _back(project_id, f"リサーチ中断: {e}")
    get_repo().save(project)
    return _back(project_id, "リサーチが完了しました。情報源を確認してください")


@app.post("/projects/{project_id}/to_script")
def to_script(project_id: str, user: str = Depends(current_user)):
    """リサーチ確認済み(人間)→台本生成→台本確認待ちへ。"""
    project = _load(project_id)
    try:
        states.transition(project, states.SCRIPTING, actor=user, note="リサーチ確認済み")
        scripting.run(project)
        states.transition(project, states.SCRIPT_REVIEW, actor=user)
    except (states.StateError, CostLimitExceeded, LLMError) as e:
        get_repo().save(project)
        return _back(project_id, str(e))
    get_repo().save(project)
    return _back(project_id, "台本を生成しました。内容を確認してください")


@app.post("/projects/{project_id}/script_edit")
async def script_edit(project_id: str, request: Request,
                      user: str = Depends(current_user)):
    project = _load(project_id)
    form = await request.form()
    key = form.get("key")
    for sec in project.script:
        if sec.key == key:
            sec.narration = form.get("narration", sec.narration)
            sec.on_screen_text = form.get("on_screen_text", sec.on_screen_text)
            project.log(f"台本を修正({sec.name})", actor=user)
    get_repo().save(project)
    return _back(project_id, "台本を保存しました")


@app.post("/projects/{project_id}/regenerate_script")
def regenerate_script(project_id: str, user: str = Depends(current_user)):
    """差し戻し後の台本再生成。直近の差し戻し理由をプロンプトに反映する。"""
    project = _load(project_id)
    if project.status != states.SCRIPTING:
        return _back(project_id, "台本の再生成は「台本作成中」でのみ実行できます")
    feedback = next(
        (a.reason for a in reversed(project.approvals)
         if a.stage == "台本確認" and a.decision == "rejected"), "")
    try:
        scripting.run(project, feedback=feedback)
        states.transition(project, states.SCRIPT_REVIEW, actor=user)
    except (CostLimitExceeded, LLMError, states.StateError) as e:
        get_repo().save(project)
        return _back(project_id, f"台本再生成に失敗: {e}")
    get_repo().save(project)
    return _back(project_id, "台本を再生成しました。内容を確認してください")


@app.post("/projects/{project_id}/script_decision")
def script_decision(project_id: str, decision: str = Form(...),
                    reason: str = Form(""), user: str = Depends(current_user)):
    project = _load(project_id)
    try:
        if decision == "approve":
            approval.approve_script(project, user, reason)
            storyboard.build(project)
            display.plan(project)
            msg = "台本を承認しました。素材生成に進めます"
        else:
            approval.reject_script(project, user, reason)
            msg = "台本を差し戻しました"
    except (states.StateError, approval.ApprovalError) as e:
        return _back(project_id, str(e))
    get_repo().save(project)
    return _back(project_id, msg)


@app.post("/projects/{project_id}/generate_assets")
def generate_assets(project_id: str, user: str = Depends(current_user)):
    project = _load(project_id)
    if project.status != states.ASSETS:
        return _back(project_id, f"素材生成は「{states.ASSETS}」でのみ実行できます")
    if not project.scenes:
        storyboard.build(project)
    try:
        media.generate_all(project)
        msg = f"素材生成が完了しました(累計 ¥{project.total_cost()})"
    except CostLimitExceeded as e:
        msg = f"{e} — コスト承認後に再開できます"
    except Exception as e:  # 生成APIの失敗は案件を壊さず再実行可能にする
        project.log("素材生成エラー", ok=False, note=str(e)[:300])
        msg = f"素材生成エラー(生成済み分は保存済み。再実行で続きから): {str(e)[:200]}"
    get_repo().save(project)
    return _back(project_id, msg)


@app.post("/projects/{project_id}/regenerate_images")
def regenerate_images(project_id: str, replace_video: str = Form(""),
                      user: str = Depends(current_user)):
    """画像素材のみ無効化して再生成できる状態に戻す(音声・BGMは保持)。

    replace_video 指定時はAI動画シーンを静止画に変更し、動画素材も無効化する
    (Veo再生成費をかけずに偽ロゴ入りクリップを差し替えるための低コスト経路)。
    """
    project = _load(project_id)
    allowed = {states.ASSETS, states.EDITING, states.QA}
    if project.status not in allowed:
        return _back(project_id, "画像再生成は素材生成中/編集中/品質確認中でのみ実行できます")
    kinds = {"image", "thumbnail"}
    note = "音声/AI動画/BGMは保持"
    if replace_video:
        kinds.add("video")
        for scene in project.scenes:
            if scene.type == "ai_video":
                scene.type = "still_motion"
        note = "AI動画シーンは静止画に変更・音声/BGMは保持"
    storyboard.refresh_visual_prompts(project)  # 生成指示文を現行テンプレートで引き直す
    if not any(motion_has(s.display) for s in project.scenes):
        display.plan(project)  # 旧案件には演出プランが無いのでここで付与
    count = 0
    for a in project.assets:
        if a.stage == "assets" and a.kind in kinds and a.adopted:
            a.adopted = False
            count += 1
    old = project.status
    project.status = states.ASSETS
    project.log(f"画像系素材{count}件を無効化({old}から素材生成中へ・{note})", actor=user)
    get_repo().save(project)
    return _back(project_id, f"{count}件を無効化しました。「素材生成を実行」で再生成されます")


@app.post("/projects/{project_id}/cost_override")
def cost_override(project_id: str, user: str = Depends(current_user)):
    """上限超過の続行承認(要件10章: 人間の確認)。"""
    project = _load(project_id)
    project.cost_limit_override_approved = True
    project.cost_stop_reason = ""
    project.log("コスト上限の超過を承認", actor=user)
    get_repo().save(project)
    return _back(project_id, "上限超過を承認しました。素材生成を再実行してください")


@app.post("/projects/{project_id}/render")
def run_render(project_id: str, user: str = Depends(current_user)):
    project = _load(project_id)
    try:
        if project.status != states.EDITING:  # 編集中からの再レンダリングを許容
            states.transition(project, states.EDITING, actor=user)
        render.run(project)
        states.transition(project, states.QA, actor=user, note="レンダリング完了")
    except (states.StateError, RuntimeError) as e:
        get_repo().save(project)
        return _back(project_id, f"編集処理に失敗: {e}")
    get_repo().save(project)
    return _back(project_id, "編集が完了しました。品質確認へ進んでください")


@app.get("/projects/{project_id}/quality", response_class=HTMLResponse)
def quality_page(project_id: str, request: Request,
                 user: str = Depends(current_user)):
    project = _load(project_id)
    render_asset = media.find_asset(project, "editing", None, "render")
    subtitle_asset = media.find_asset(project, "editing", None, "subtitle")
    return templates.TemplateResponse(request, "quality.html", {
        "p": project, "user": user, "storage": get_storage(),
        "render_asset": render_asset, "subtitle_asset": subtitle_asset,
        "checklist": approval.QUALITY_CHECKLIST,
        "rollback_targets": states.ROLLBACK_TARGETS,
        "msg": request.query_params.get("msg", ""),
    })


@app.post("/projects/{project_id}/quality")
async def quality_submit(project_id: str, request: Request,
                         user: str = Depends(current_user)):
    project = _load(project_id)
    form = dict(await request.form())
    checklist = _checklist_from(form, approval.QUALITY_CHECKLIST)
    ok = form.get("decision") == "ok"
    try:
        approval.submit_quality(project, user, checklist, ok,
                                reason=form.get("reason", ""),
                                rollback_to=form.get("rollback_to", ""))
    except (approval.ApprovalError, states.StateError) as e:
        return RedirectResponse(
            f"/projects/{project_id}/quality?msg={quote(str(e))}", status_code=303)
    get_repo().save(project)
    return _back(project_id, "品質確認を記録しました")


@app.get("/projects/{project_id}/approval", response_class=HTMLResponse)
def approval_page(project_id: str, request: Request,
                  user: str = Depends(current_user)):
    project = _load(project_id)
    render_asset = media.find_asset(project, "editing", None, "render")
    thumb = media.find_asset(project, "assets", None, "thumbnail")
    return templates.TemplateResponse(request, "approval.html", {
        "p": project, "user": user, "storage": get_storage(),
        "render_asset": render_asset, "thumb": thumb,
        "checklist": approval.PUBLISH_CHECKLIST,
        "rollback_targets": states.ROLLBACK_TARGETS,
        "msg": request.query_params.get("msg", ""),
    })


@app.post("/projects/{project_id}/publish_info")
async def publish_info_edit(project_id: str, request: Request,
                            user: str = Depends(current_user)):
    project = _load(project_id)
    form = dict(await request.form())
    pi = project.publish_info
    pi.title = form.get("title", pi.title)
    pi.description = form.get("description", pi.description)
    pi.tags = [t.strip() for t in form.get("tags", "").split(",") if t.strip()]
    project.log("投稿情報を修正", actor=user)
    get_repo().save(project)
    return RedirectResponse(
        f"/projects/{project_id}/approval?msg={quote('投稿情報を保存しました')}",
        status_code=303)


@app.post("/projects/{project_id}/approval")
async def approval_submit(project_id: str, request: Request,
                          user: str = Depends(current_user)):
    project = _load(project_id)
    form = dict(await request.form())
    checklist = _checklist_from(form, approval.PUBLISH_CHECKLIST)
    decision = "approved" if form.get("decision") == "approve" else "rejected"
    try:
        approval.submit_publish(project, user, checklist, decision,
                                reason=form.get("reason", ""),
                                rollback_to=form.get("rollback_to", ""))
    except (approval.ApprovalError, states.StateError) as e:
        return RedirectResponse(
            f"/projects/{project_id}/approval?msg={quote(str(e))}", status_code=303)
    get_repo().save(project)
    msg = "公開を承認しました" if decision == "approved" else "差し戻しました"
    return _back(project_id, msg)


@app.get("/projects/{project_id}/analytics", response_class=HTMLResponse)
def analytics_page(project_id: str, request: Request,
                   user: str = Depends(current_user)):
    project = _load(project_id)
    data = analytics.fetch(project)
    return templates.TemplateResponse(request, "analytics.html", {
        "p": project, "user": user, "data": data,
    })


@app.post("/projects/{project_id}/state")
def change_state(project_id: str, target: str = Form(...), reason: str = Form(""),
                 user: str = Depends(current_user)):
    """保留・中止・再開・修正必要からの差し戻しなどの手動遷移。"""
    project = _load(project_id)
    try:
        if project.status in states.ROLLBACK_SOURCES and target in states.ROLLBACK_TARGETS:
            states.rollback(project, target, reason=reason or "手動差し戻し", actor=user)
        else:
            states.transition(project, target, actor=user, note=reason)
    except states.StateError as e:
        return _back(project_id, str(e))
    get_repo().save(project)
    return _back(project_id, f"状態を「{target}」にしました")


@app.get("/media/{name:path}")
def media_file(name: str, user: str = Depends(current_user)):
    data = get_storage().read(name)
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return Response(content=data, media_type=mime)


@app.get("/healthz")
def healthz():
    return {"ok": True}
