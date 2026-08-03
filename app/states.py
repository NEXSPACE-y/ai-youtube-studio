"""案件の状態機械(要件7章の12状態)と差し戻し規則(追補5章)。"""

from app.models import Project, RollbackRecord

PLANNING = "企画中"
RESEARCH = "調査中"
SCRIPTING = "台本作成中"
SCRIPT_REVIEW = "台本確認待ち"
ASSETS = "素材生成中"
EDITING = "編集中"
QA = "品質確認中"
APPROVAL = "公開承認待ち"
PUBLISHED = "投稿済み"
NEEDS_FIX = "修正必要"
ON_HOLD = "保留"
CANCELLED = "中止"

ALL_STATES = [
    PLANNING, RESEARCH, SCRIPTING, SCRIPT_REVIEW, ASSETS, EDITING,
    QA, APPROVAL, PUBLISHED, NEEDS_FIX, ON_HOLD, CANCELLED,
]

# 通常の前進遷移 + 保留/中止
TRANSITIONS: dict[str, set[str]] = {
    PLANNING: {RESEARCH, ON_HOLD, CANCELLED},
    RESEARCH: {SCRIPTING, PLANNING, ON_HOLD, CANCELLED},
    SCRIPTING: {SCRIPT_REVIEW, ON_HOLD, CANCELLED},
    SCRIPT_REVIEW: {ASSETS, SCRIPTING, NEEDS_FIX, ON_HOLD, CANCELLED},
    ASSETS: {EDITING, NEEDS_FIX, ON_HOLD, CANCELLED},
    EDITING: {QA, NEEDS_FIX, ON_HOLD, CANCELLED},
    QA: {APPROVAL, NEEDS_FIX, ON_HOLD, CANCELLED},
    APPROVAL: {PUBLISHED, NEEDS_FIX, ON_HOLD, CANCELLED},
    PUBLISHED: {NEEDS_FIX},
    NEEDS_FIX: {PLANNING, RESEARCH, SCRIPTING, ASSETS, EDITING, QA, ON_HOLD, CANCELLED},
    ON_HOLD: {PLANNING, RESEARCH, SCRIPTING, SCRIPT_REVIEW, ASSETS, EDITING, QA, APPROVAL, CANCELLED},
    CANCELLED: set(),
}

# 差し戻し先として許される制作工程
ROLLBACK_TARGETS = [PLANNING, RESEARCH, SCRIPTING, ASSETS, EDITING, QA]

# 差し戻し元として許される確認系工程
ROLLBACK_SOURCES = {SCRIPT_REVIEW, QA, APPROVAL, PUBLISHED, NEEDS_FIX}

# 工程の順序(下流成果物の無効化判定に使用)
_STAGE_ORDER = [PLANNING, RESEARCH, SCRIPTING, ASSETS, EDITING, QA]
_ASSET_STAGE_OF = {
    PLANNING: "planning", RESEARCH: "research", SCRIPTING: "script",
    ASSETS: "assets", EDITING: "editing", QA: "qa",
}


class StateError(Exception):
    pass


def assert_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, set()):
        raise StateError(f"不正な状態遷移: {current} → {target}")


def transition(project: Project, target: str, actor: str = "system", note: str = "") -> None:
    assert_transition(project.status, target)
    old = project.status
    project.status = target
    project.log(f"状態変更 {old} → {target}", actor=actor, note=note)


def rollback(project: Project, to_status: str, reason: str, fix_target: str = "",
             actor: str = "system") -> RollbackRecord:
    """確認工程からの差し戻し。下流成果物を不採用化し、監査記録を残す(追補5章)。

    成果物は削除せず adopted=False で保持する。
    """
    if project.status not in ROLLBACK_SOURCES:
        raise StateError(f"差し戻し不可の状態: {project.status}")
    if to_status not in ROLLBACK_TARGETS:
        raise StateError(f"差し戻し先が不正: {to_status}")
    if not reason.strip():
        raise StateError("差し戻し理由は必須")

    target_idx = _STAGE_ORDER.index(to_status)
    downstream_stages = {_ASSET_STAGE_OF[s] for s in _STAGE_ORDER[target_idx:]}
    reusable, invalidated = [], []
    for a in project.assets:
        if a.stage in downstream_stages and a.adopted:
            a.adopted = False
            invalidated.append(a.id)
        else:
            reusable.append(a.id)

    rec = RollbackRecord(
        from_status=project.status, to_status=to_status, reason=reason,
        fix_target=fix_target, reusable_assets=reusable, invalidated_assets=invalidated,
    )
    project.rollbacks.append(rec)
    old = project.status
    project.status = to_status
    project.log(f"差し戻し {old} → {to_status}: {reason}", actor=actor)
    return rec
