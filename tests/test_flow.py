"""E2E: 企画→リサーチ→台本→素材→編集→品質確認→公開承認(豆虎Gate)→投稿済み。

初期検証要件(要件14章)のローカル版に相当する。
"""

import pytest
from fastapi.testclient import TestClient

from app.services.approval import PUBLISH_CHECKLIST, QUALITY_CHECKLIST
from app.web.app import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app, follow_redirects=True)


@pytest.fixture(scope="module")
def project_id(client):
    r = client.post("/projects", data={"theme": "テスト用のダミーテーマ"})
    assert r.status_code == 200
    from app.repo import get_repo

    return get_repo().list_all()[0].id


def _status(pid):
    from app.repo import get_repo

    return get_repo().get(pid).status


def test_full_pipeline(client, project_id):
    pid = project_id
    assert _status(pid) == "企画中"

    # 企画採用 → 調査
    client.post(f"/projects/{pid}/decide", data={"decision": "採用"})
    assert _status(pid) == "調査中"
    client.post(f"/projects/{pid}/research")

    # 情報源確認 → 台本生成
    client.post(f"/projects/{pid}/to_script")
    assert _status(pid) == "台本確認待ち"

    # 台本承認 → 素材生成
    client.post(f"/projects/{pid}/script_decision",
                data={"decision": "approve", "reason": ""})
    assert _status(pid) == "素材生成中"
    client.post(f"/projects/{pid}/generate_assets")

    from app.repo import get_repo

    p = get_repo().get(pid)
    assert p.scenes, "シーンが構成されていること"
    assert any(a.kind == "narration" for a in p.assets)
    assert any(a.kind == "thumbnail" for a in p.assets)
    # 保存要件(8章): 命名から案件・工程・シーン・版が識別できる
    narr = next(a for a in p.assets if a.kind == "narration")
    assert narr.path.startswith(f"{pid}/assets/scene")
    assert "/v1/" in narr.path

    # 編集 → 品質確認
    client.post(f"/projects/{pid}/render")
    assert _status(pid) == "品質確認中"
    p = get_repo().get(pid)
    assert any(a.kind == "render" for a in p.assets)
    assert any(a.kind == "subtitle" for a in p.assets)

    # 品質確認合格 → 公開承認待ち(投稿情報が生成される)
    chk = {f"chk_{k}": "on" for k, _ in QUALITY_CHECKLIST}
    client.post(f"/projects/{pid}/quality", data={**chk, "decision": "ok"})
    assert _status(pid) == "公開承認待ち"
    p = get_repo().get(pid)
    assert p.publish_info.title
    assert p.publish_info.ai_disclosure_note in p.publish_info.description

    # チェック不足では公開できない(人間Gate)
    client.post(f"/projects/{pid}/approval", data={"decision": "approve"})
    assert _status(pid) == "公開承認待ち"

    # 全チェックで承認 → 投稿済み
    chk = {f"chk_{k}": "on" for k, _ in PUBLISH_CHECKLIST}
    client.post(f"/projects/{pid}/approval", data={**chk, "decision": "approve"})
    assert _status(pid) == "投稿済み"
    p = get_repo().get(pid)
    assert p.publish_info.youtube_video_id.startswith("LOCAL-")
    assert any(a.stage == "公開承認" and a.decision == "approved" for a in p.approvals)

    # 費用が算出できる(受入条件7)
    assert isinstance(p.total_cost(), float)


def test_rollback_from_published(client, project_id):
    pid = project_id
    client.post(f"/projects/{pid}/state",
                data={"target": "修正必要", "reason": "字幕の誤字"})
    assert _status(pid) == "修正必要"
    client.post(f"/projects/{pid}/state",
                data={"target": "編集中", "reason": "字幕修正のため"})
    assert _status(pid) == "編集中"


def test_script_reject_and_regenerate(client):
    """台本差し戻し→再生成→再度確認待ちに戻れること(受入条件8)。"""
    from app.repo import get_repo

    before = {p.id for p in get_repo().list_all()}
    client.post("/projects", data={"theme": "差し戻しテスト用テーマ"})
    pid = next(p.id for p in get_repo().list_all() if p.id not in before)
    client.post(f"/projects/{pid}/decide", data={"decision": "採用"})
    client.post(f"/projects/{pid}/research")
    client.post(f"/projects/{pid}/to_script")
    assert _status(pid) == "台本確認待ち"

    # 差し戻し(理由必須)
    client.post(f"/projects/{pid}/script_decision",
                data={"decision": "reject", "reason": "転換点が弱い"})
    assert _status(pid) == "台本作成中"

    # 再生成で確認待ちへ戻る
    client.post(f"/projects/{pid}/regenerate_script")
    assert _status(pid) == "台本確認待ち"

    p = get_repo().get(pid)
    assert any(a.decision == "rejected" and a.reason == "転換点が弱い"
               for a in p.approvals)
