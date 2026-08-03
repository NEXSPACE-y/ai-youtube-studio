"""絵コンテ工程(docs/09 フェーズ1)のモデル・状態機械を検証する。

重点は「既存案件を壊さないこと」。絵コンテ工程は任意であり、
中割りカットを含まない案件は従来どおりの経路を通れなければならない。
"""
import pytest

from app import states
from app.models import Asset, Project, Scene


def _project(status: str = states.PLANNING) -> Project:
    return Project(theme="テスト", status=status)


# ---------- モデル ----------

def test_絵コンテ用フィールドは既定値を持つ():
    """既存の保存済み案件(新フィールドを含まないJSON)がそのまま読めること。"""
    s = Scene(no=1)
    assert s.cast == []
    assert s.acting == "" and s.camera == ""
    assert s.keyframe_a_prompt == "" and s.keyframe_b_prompt == ""


def test_castとspeakerは別概念():
    # ツヅリは映るが喋らない(docs/07)
    s = Scene(no=1, speaker="栞", cast=["栞", "ツヅリ"])
    assert s.speaker == "栞"
    assert "ツヅリ" in s.cast and s.speaker != "ツヅリ"


def test_castは他シーンと共有されない():
    a, b = Scene(no=1), Scene(no=2)
    a.cast.append("栞")
    assert b.cast == []


# ---------- 状態機械 ----------

def test_絵コンテ工程を通る経路():
    p = _project(states.SCRIPT_REVIEW)
    states.transition(p, states.STORYBOARD)
    states.transition(p, states.STORYBOARD_REVIEW)
    states.transition(p, states.ASSETS)
    assert p.status == states.ASSETS


def test_絵コンテを飛ばす既存経路が残っている():
    p = _project(states.SCRIPT_REVIEW)
    states.transition(p, states.ASSETS)
    assert p.status == states.ASSETS


def test_絵コンテ確認から作成中へ戻せる():
    p = _project(states.STORYBOARD_REVIEW)
    states.transition(p, states.STORYBOARD)
    assert p.status == states.STORYBOARD


def test_絵コンテ作成中から素材生成中へは飛べない():
    """Gateを迂回できないこと。"""
    p = _project(states.STORYBOARD)
    with pytest.raises(states.StateError):
        states.transition(p, states.ASSETS)


def test_新状態がALL_STATESに含まれる():
    assert states.STORYBOARD in states.ALL_STATES
    assert states.STORYBOARD_REVIEW in states.ALL_STATES


# ---------- 差し戻し ----------

def test_絵コンテ確認から差し戻せる():
    p = _project(states.STORYBOARD_REVIEW)
    rec = states.rollback(p, states.STORYBOARD, reason="原画のキャラが崩れている")
    assert p.status == states.STORYBOARD
    assert rec.to_status == states.STORYBOARD


def test_絵コンテへの差し戻しで下流成果物が不採用になる():
    p = _project(states.QA)
    p.assets = [
        Asset(stage="script", kind="text"),
        Asset(stage="storyboard", kind="keyframe_a", scene_no=1),
        Asset(stage="assets", kind="video", scene_no=1),
        Asset(stage="editing", kind="render"),
    ]
    states.rollback(p, states.STORYBOARD, reason="演出をやり直す")
    adopted = {a.stage: a.adopted for a in p.assets}
    assert adopted["script"] is True          # 上流は残る
    assert adopted["storyboard"] is False     # 差し戻し先以降は不採用
    assert adopted["assets"] is False
    assert adopted["editing"] is False


def test_素材への差し戻しでは原画が残る():
    """原画は素材より上流。動画だけ撮り直すとき原画を捨てさせない。"""
    p = _project(states.QA)
    p.assets = [
        Asset(stage="storyboard", kind="keyframe_a", scene_no=1),
        Asset(stage="assets", kind="video", scene_no=1),
    ]
    states.rollback(p, states.ASSETS, reason="動画だけ撮り直す")
    adopted = {a.stage: a.adopted for a in p.assets}
    assert adopted["storyboard"] is True
    assert adopted["assets"] is False
