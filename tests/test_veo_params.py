"""_veo_video が Veo に渡すconfigの組み立てを検証する(APIは叩かない)。

docs/06 §3 の中割り(原画A→B)と参照画像による一貫性確保を、
アプリ本体から使えることを担保する。実地検証の記録は docs/08_中割り検証_20260803.md。
"""
from app.services import media


class _FakeVideo:
    video_bytes = b"mp4"


class _FakeOp:
    done = True
    response = type("R", (), {"generated_videos": [type("V", (), {"video": _FakeVideo})]})


class _FakeClient:
    """generate_videos に渡された引数を捕まえるだけのクライアント。"""

    def __init__(self):
        self.captured = {}
        outer = self

        class _Models:
            def generate_videos(self, **kwargs):
                outer.captured = kwargs
                return _FakeOp()

        self.models = _Models()


def _call(monkeypatch, **kwargs):
    fake = _FakeClient()
    monkeypatch.setattr(media, "_media_client", lambda _loc: fake)
    data = media._veo_video("テストプロンプト", 8, **kwargs)
    assert data == b"mp4"
    return fake.captured


def test_未指定なら余計なパラメータを載せない(monkeypatch):
    cfg = _call(monkeypatch)["config"]
    assert cfg.aspect_ratio == "16:9"
    assert cfg.duration_seconds == 8
    assert cfg.last_frame is None
    assert cfg.reference_images is None
    assert cfg.seed is None


def test_音声は既定で生成しない(monkeypatch):
    # render.py が `-map 0:v -map 1:a` で音声をTTSから取るため、Veoの音声は捨てられる
    assert _call(monkeypatch)["config"].generate_audio is False
    assert _call(monkeypatch, generate_audio=True)["config"].generate_audio is True


def test_始点のみ指定は従来どおり(monkeypatch):
    captured = _call(monkeypatch, image_bytes=b"A")
    assert captured["image"].image_bytes == b"A"
    assert captured["config"].last_frame is None


def test_中割り_始点と終点を渡せる(monkeypatch):
    captured = _call(monkeypatch, image_bytes=b"A", last_frame_bytes=b"B")
    assert captured["image"].image_bytes == b"A"
    assert captured["config"].last_frame.image_bytes == b"B"


def test_参照画像とseedを渡せる(monkeypatch):
    cfg = _call(monkeypatch, reference_bytes=[b"c1", b"c2"], seed=20260803)["config"]
    assert [r.image.image_bytes for r in cfg.reference_images] == [b"c1", b"c2"]
    assert all(r.reference_type == "ASSET" for r in cfg.reference_images)
    assert cfg.seed == 20260803


def test_参照タイプにSTYLEを指定できる(monkeypatch):
    cfg = _call(monkeypatch, reference_bytes=[b"s"], reference_type="STYLE")["config"]
    assert cfg.reference_images[0].reference_type == "STYLE"


def test_seedは0でも載る(monkeypatch):
    assert _call(monkeypatch, seed=0)["config"].seed == 0
