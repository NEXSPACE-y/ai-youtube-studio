from app.models import Project, Scene
from app.services import display
from app.services.motion import FPS, H, W, ease_out_back, ease_out_cubic, has_display, render_frames


def test_easing_bounds():
    for fn in (ease_out_cubic, ease_out_back):
        assert fn(0.0) == 0.0 or abs(fn(0.0)) < 0.01
        assert abs(fn(1.0) - 1.0) < 0.01
        assert fn(-1) is not None and fn(2) is not None  # 範囲外でも例外を出さない


def test_has_display():
    assert not has_display({})
    assert not has_display({"template": "none"})
    assert has_display({"template": "bullets"})


def test_render_frames_shape_and_count():
    disp = {"template": "bullets", "title": "テスト見出し",
            "items": ["項目一", "項目二", "項目三"]}
    dur = 2.0
    frames = list(render_frames(disp, None, dur))
    assert len(frames) == int(dur * FPS)
    assert all(len(f) == W * H * 3 for f in frames)


def test_render_all_templates():
    for template in ("title_card", "keyword_pop", "bullets", "compare_cards"):
        disp = {"template": template, "title": "見出し", "items": ["A", "B"]}
        first = next(iter(render_frames(disp, None, 0.5)))
        assert len(first) == W * H * 3


def test_display_stub_assigns_all_scenes():
    p = Project(title="t", theme="th")
    p.scenes = [Scene(no=1, section_key="hook", narration="n"),
                Scene(no=2, section_key="thesis", narration="n"),
                Scene(no=3, section_key="progression", narration="n")]
    display._stub(p)
    assert all(s.display.get("template") for s in p.scenes)


def test_sanitize_limits():
    raw = {"template": "怪しいテンプレ", "title": "x" * 99,
           "items": [f"item{i}" * 20 for i in range(9)]}
    clean = display._sanitize(raw)
    assert clean["template"] == "none"
    assert len(clean["title"]) <= display.MAX_TITLE
    assert len(clean["items"]) <= display.MAX_ITEMS
    assert all(len(i) <= display.MAX_ITEM_CHARS for i in clean["items"])
