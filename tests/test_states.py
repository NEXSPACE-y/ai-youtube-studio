import pytest

from app import states
from app.models import Asset, Project


def _project(status: str) -> Project:
    return Project(title="t", theme="th", status=status)


def test_valid_transition():
    p = _project(states.PLANNING)
    states.transition(p, states.RESEARCH)
    assert p.status == states.RESEARCH
    assert any("状態変更" in h.action for h in p.history)


def test_invalid_transition_raises():
    p = _project(states.PLANNING)
    with pytest.raises(states.StateError):
        states.transition(p, states.PUBLISHED)


def test_published_can_only_go_to_needs_fix():
    p = _project(states.PUBLISHED)
    with pytest.raises(states.StateError):
        states.transition(p, states.PLANNING)
    states.transition(p, states.NEEDS_FIX)
    assert p.status == states.NEEDS_FIX


def test_rollback_requires_reason():
    p = _project(states.QA)
    with pytest.raises(states.StateError):
        states.rollback(p, states.SCRIPTING, reason=" ")


def test_rollback_invalidates_downstream_assets_only():
    p = _project(states.QA)
    up = Asset(stage="research", kind="note", path="a")
    down1 = Asset(stage="assets", scene_no=1, kind="image", path="b")
    down2 = Asset(stage="editing", kind="render", path="c")
    p.assets = [up, down1, down2]

    rec = states.rollback(p, states.SCRIPTING, reason="台本の事実誤認")

    assert p.status == states.SCRIPTING
    assert up.adopted is True
    assert down1.adopted is False and down2.adopted is False
    assert set(rec.invalidated_assets) == {down1.id, down2.id}
    assert up.id in rec.reusable_assets
    # 成果物は削除されず保持される(追補5章)
    assert len(p.assets) == 3


def test_rollback_from_invalid_state():
    p = _project(states.PLANNING)
    with pytest.raises(states.StateError):
        states.rollback(p, states.RESEARCH, reason="x")


def test_rollback_to_invalid_target():
    p = _project(states.APPROVAL)
    with pytest.raises(states.StateError):
        states.rollback(p, states.PUBLISHED, reason="x")
