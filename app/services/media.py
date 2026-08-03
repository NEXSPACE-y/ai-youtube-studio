"""素材生成(要件5.5)。クラウド=Vertex AI各モデル / ローカル=ダミー素材。

再実行時は採用済み素材があるシーンをスキップするため、コスト上限停止(要件10章)
からの再開や部分的な再生成が可能。
"""

from __future__ import annotations

import io
import struct
import time
from typing import Optional, Sequence

from app.config import settings
from app.costs import CostMeter
from app.models import Asset, Project, Scene
from app.storage import get_storage, object_name

AI_VIDEO_MAX_SEC = 8  # Veoに依頼する1クリップの上限秒数(追補2章のコスト抑制)
BGM_SECONDS = 30
NARRATION_SEC_PER_CHAR = 0.16  # ローカルダミー音声の長さ目安


def _save_asset(project: Project, stage: str, scene_no: Optional[int], kind: str,
                filename: str, data: bytes, cost_jpy: float = 0.0,
                meta: Optional[dict] = None) -> Asset:
    version = project.next_asset_version(stage, scene_no, kind)
    name = object_name(project.id, stage, scene_no, version, filename)
    get_storage().write(name, data)
    asset = Asset(stage=stage, scene_no=scene_no, version=version, kind=kind,
                  path=name, cost_jpy=cost_jpy, meta=meta or {})
    project.assets.append(asset)
    return asset


def find_asset(project: Project, stage: str, scene_no: Optional[int], kind: str) -> Optional[Asset]:
    hits = [a for a in project.assets
            if a.stage == stage and a.scene_no == scene_no and a.kind == kind and a.adopted]
    return max(hits, key=lambda a: a.version) if hits else None


# ---------- ローカルダミー生成 ----------

_SCENE_COLORS = {"ai_video": (72, 42, 84), "still_motion": (36, 56, 84), "diagram": (30, 72, 60), "text": (60, 60, 60)}
_TYPE_LABEL = {"ai_video": "AI動画(ダミー静止画)", "still_motion": "静止画+モーション", "diagram": "図解", "text": "テキスト"}


def _font(size: int):
    from PIL import ImageFont

    for path in (r"C:\Windows\Fonts\meiryo.ttc", r"C:\Windows\Fonts\msgothic.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                 "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _placeholder_image(title: str, label: str, body: str, color: tuple) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1280, 720), color)
    d = ImageDraw.Draw(img)
    d.text((40, 40), title, font=_font(40), fill=(255, 255, 255))
    d.text((40, 110), label, font=_font(28), fill=(255, 220, 120))
    y = 180
    for i in range(0, min(len(body), 120), 30):
        d.text((40, y), body[i:i + 30], font=_font(24), fill=(220, 220, 220))
        y += 40
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _silent_wav(seconds: float, rate: int = 24000) -> bytes:
    n = int(seconds * rate)
    data = b"\x00\x00" * n
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(data), b"WAVE", b"fmt ", 16,
        1, 1, rate, rate * 2, 2, 16, b"data", len(data),
    )
    return header + data


# ---------- クラウド生成(Vertex AI) ----------

def _with_backoff(fn, attempts: int = 5, base_wait: float = 15.0):
    """429(クォータ超過)を自動リトライする。他のエラーは即時raise。"""
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            is_quota = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
            if not is_quota or i == attempts - 1:
                raise
            time.sleep(base_wait * (2 ** i))  # 15→30→60→120秒
    raise RuntimeError("リトライ上限に到達")


_clients: dict[str, object] = {}


def _media_client(location: str):
    """genaiクライアントはリージョンごとに1個を使い回す。

    呼び出しごとに生成するとSDK内部の共有HTTP接続がGCで閉じられ、
    後続呼び出しが "client has been closed" で失敗するため。
    """
    if location not in _clients:
        from google import genai

        _clients[location] = genai.Client(
            vertexai=True, project=settings.gcp_project, location=location)
    return _clients[location]


def _veo_video(prompt: str, seconds: int,
               image_bytes: Optional[bytes] = None,
               last_frame_bytes: Optional[bytes] = None,
               reference_bytes: Optional[Sequence[bytes]] = None,
               reference_type: str = "ASSET",
               seed: Optional[int] = None,
               generate_audio: bool = False) -> bytes:
    """Veo動画生成。

    - image_bytes         始点フレーム。指定時はその画像を起点に生成する
    - last_frame_bytes    終点フレーム。始点と併せて指定すると「原画A→B」の中割りになる
                          (docs/06 §3。生成の暴れる余地が構造的に小さくなる)
    - reference_bytes     キャラ・画風の参照画像。カット間の一貫性を保つ
                          reference_type は "ASSET"(被写体) か "STYLE"(画風)
    - seed                再現性の確保
    - generate_audio      既定False。編集(render.py)は `-map 0:v -map 1:a` で
                          映像だけをクリップから取り、音声はTTSナレーションを使う。
                          Veoの音声は完成mp4に入らないため、生成しない

    指定しなかった項目はconfigに載せない(APIの既定に委ねる)。
    """
    from google.genai import types

    def _img(data: bytes):
        return types.Image(image_bytes=data, mime_type="image/png")

    client = _media_client(settings.media_region)
    cfg: dict = {"aspect_ratio": "16:9", "duration_seconds": seconds,
                 "generate_audio": generate_audio}
    if last_frame_bytes:
        cfg["last_frame"] = _img(last_frame_bytes)
    if reference_bytes:
        cfg["reference_images"] = [
            types.VideoGenerationReferenceImage(image=_img(b),
                                                reference_type=reference_type)
            for b in reference_bytes
        ]
    if seed is not None:
        cfg["seed"] = seed
    kwargs = {}
    if image_bytes:
        kwargs["image"] = _img(image_bytes)
    op = client.models.generate_videos(
        model=settings.veo_model, prompt=prompt,
        config=types.GenerateVideosConfig(**cfg),
        **kwargs,
    )
    while not op.done:
        time.sleep(10)
        op = client.operations.get(op)
    return op.response.generated_videos[0].video.video_bytes


def _mascot_bytes() -> Optional[bytes]:
    if not settings.mascot_object:
        return None
    try:
        return get_storage().read(settings.mascot_object)
    except Exception:
        return None


_imagen_region: list[str] = []  # 初回に使えたリージョンを記憶


def _image_config():
    from google.genai import types

    kwargs = {"response_modalities": ["TEXT", "IMAGE"]}
    if hasattr(types, "ImageConfig"):  # SDKが対応していればアスペクト比を明示
        try:
            return types.GenerateContentConfig(
                **kwargs, image_config=types.ImageConfig(aspect_ratio="16:9"))
        except (TypeError, ValueError):
            pass
    return types.GenerateContentConfig(**kwargs)


def _imagen_image(prompt: str) -> bytes:
    """画像生成(gemini-2.5-flash-image系のgenerateContent方式)。"""
    from google.genai.errors import ClientError

    prompt = f"{prompt} Wide 16:9 composition."
    regions = _imagen_region or [settings.media_region, settings.gcp_region]
    last_err: Exception | None = None
    for region in regions:
        try:
            resp = _media_client(region).models.generate_content(
                model=settings.imagen_model, contents=prompt,
                config=_image_config())
            for part in resp.candidates[0].content.parts:
                if getattr(part, "inline_data", None) and part.inline_data.data:
                    if not _imagen_region:
                        _imagen_region.append(region)
                    return part.inline_data.data
            raise RuntimeError("画像がレスポンスに含まれていません")
        except ClientError as e:
            last_err = e
    raise last_err or RuntimeError("画像生成に失敗しました")


def _wav_wrap(pcm: bytes, rate: int = 24000) -> bytes:
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16,
        1, 1, rate, rate * 2, 2, 16, b"data", len(pcm))
    return header + pcm


def _gemini_tts(text: str, voice: str = "", style: str = "") -> tuple[bytes, float]:
    """Gemini-TTS: 演技指示(style)を前置きして読み上げさせる。出力PCM 24kHz。"""
    from google.genai import types

    client = _media_client(settings.media_region)
    resp = client.models.generate_content(
        model=settings.gemini_tts_model,
        contents=f"{style or settings.gemini_tts_style}: {text}",
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice or settings.gemini_tts_voice)))),
    )
    pcm = None
    for part in resp.candidates[0].content.parts:
        if getattr(part, "inline_data", None) and part.inline_data.data:
            pcm = part.inline_data.data
            break
    if not pcm:
        raise RuntimeError("Gemini-TTSが音声を返しませんでした")
    return _wav_wrap(pcm), max(0.5, len(pcm) / 2 / 24000)


def _voicevox_tts(text: str, speaker: int = 0) -> tuple[bytes, float]:
    """VOICEVOX(OSS)。ローカルはアプリ起動中のエンジン、本番はCloud Run上のエンジンを想定。"""
    import io as _io
    import wave

    import requests

    base = settings.voicevox_url.rstrip("/")
    spk = speaker or settings.voicevox_speaker
    q = requests.post(f"{base}/audio_query", params={"text": text, "speaker": spk},
                      timeout=60)
    q.raise_for_status()
    s = requests.post(f"{base}/synthesis", params={"speaker": spk}, json=q.json(),
                      timeout=300)
    s.raise_for_status()
    data = s.content
    with wave.open(_io.BytesIO(data)) as w:
        duration = w.getnframes() / w.getframerate()
    return data, max(0.5, duration)


def _cloud_tts(text: str) -> tuple[bytes, float]:
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()
    resp = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(
            language_code="ja-JP", name=settings.tts_voice),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=24000),
    )
    audio = resp.audio_content
    duration = max(0.5, (len(audio) - 44) / 2 / 24000)  # WAVヘッダ44byte想定
    return audio, duration


def _lyria_bgm(prompt: str) -> bytes:
    import base64

    import google.auth
    import google.auth.transport.requests
    import requests

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    region = settings.media_region
    url = (f"https://{region}-aiplatform.googleapis.com/v1/projects/"
           f"{settings.gcp_project}/locations/{region}/publishers/google/"
           f"models/{settings.lyria_model}:predict")
    resp = requests.post(
        url, headers={"Authorization": f"Bearer {creds.token}"},
        json={"instances": [{"prompt": prompt}], "parameters": {}}, timeout=300,
    )
    resp.raise_for_status()
    return base64.b64decode(resp.json()["predictions"][0]["bytesBase64Encoded"])


# ---------- 生成本体 ----------

def _gen_visual(project: Project, scene: Scene, meter: CostMeter) -> None:
    if scene.type == "ai_video" and not settings.is_local:
        seconds = min(AI_VIDEO_MAX_SEC, int(scene.duration_sec) or AI_VIDEO_MAX_SEC)
        cost = meter.charge("veo_second", seconds, "assets")
        mascot = _mascot_bytes()
        prompt = scene.visual_prompt
        if mascot:
            prompt = (f"{settings.mascot_description}. {prompt} "
                      "Keep the character's design, colors and proportions "
                      "exactly consistent with the input image.")
        data = _with_backoff(lambda: _veo_video(prompt, seconds, mascot))
        _save_asset(project, "assets", scene.no, "video", "clip.mp4", data, cost,
                    {"prompt": prompt, "seconds": seconds,
                     "mascot": bool(mascot)})
        return
    if settings.is_local:
        data = _placeholder_image(
            f"Scene {scene.no:02d}", _TYPE_LABEL.get(scene.type, scene.type),
            scene.visual_prompt, _SCENE_COLORS.get(scene.type, (50, 50, 50)))
        meta = {"prompt": scene.visual_prompt, "placeholder": True}
        if scene.type == "ai_video":
            meta["placeholder_for"] = "ai_video"
        _save_asset(project, "assets", scene.no, "image", "frame.png", data, 0.0, meta)
        return
    cost = meter.charge("imagen_image", 1, "assets")
    data = _with_backoff(lambda: _imagen_image(scene.visual_prompt))
    _save_asset(project, "assets", scene.no, "image", "frame.png", data, cost,
                {"prompt": scene.visual_prompt})


def _gen_narration(project: Project, scene: Scene, meter: CostMeter) -> None:
    # キャラ毎の固定声(CAST_JSON)。話者未指定なら既定エンジン設定を使う
    cast = settings.cast.get(scene.speaker, {}) if scene.speaker else {}
    engine = cast.get("engine", settings.tts_engine)
    if settings.is_local:
        duration = max(2.0, len(scene.narration) * NARRATION_SEC_PER_CHAR)
        data = _silent_wav(duration)
        cost = 0.0
    elif engine == "voicevox":
        cost = 0.0  # OSSエンジン(計算費のみ)
        data, duration = _voicevox_tts(scene.narration,
                                       speaker=int(cast.get("speaker", 0)))
    elif engine == "gemini":
        cost = meter.charge("tts_1k_chars", len(scene.narration) / 1000, "assets")
        data, duration = _with_backoff(lambda: _gemini_tts(
            scene.narration, voice=cast.get("voice", ""),
            style=cast.get("style", "")))
    else:
        cost = meter.charge("tts_1k_chars", len(scene.narration) / 1000, "assets")
        data, duration = _cloud_tts(scene.narration)
    scene.audio_duration_sec = round(duration, 2)
    _save_asset(project, "assets", scene.no, "narration", "narration.wav", data, cost,
                {"chars": len(scene.narration), "duration_sec": scene.audio_duration_sec})


def _gen_bgm(project: Project, meter: CostMeter) -> None:
    # Lyriaは英語プロンプトのみ対応のため、テーマ(日本語)は埋め込まない
    prompt = ("Calm minimal documentary background music, instrumental, "
              "ambient electronic, subtle, no vocals, steady tempo, "
              "suitable for a technology explainer video.")
    if settings.is_local:
        data, cost = _silent_wav(BGM_SECONDS), 0.0
    else:
        cost = meter.charge("lyria_track", 1, "assets")
        data = _lyria_bgm(prompt)
    _save_asset(project, "assets", None, "bgm", "bgm.wav", data, cost, {"prompt": prompt})


def _gen_thumbnail(project: Project, meter: CostMeter) -> None:
    # サムネも抽象背景のみ(題材語・日本語は渡さない)。タイトル文字は将来プログラムで載せる
    prompt = ("YouTube thumbnail background: dramatic abstract technology "
              "composition, deep contrast, glowing energetic core, cinematic "
              "lighting, 16:9. Strictly no text, no letters, no logos, no icons, "
              "no charts, no user interfaces, no human faces.")
    if settings.is_local:
        data, cost = _placeholder_image(project.title, "サムネイル案", prompt, (84, 42, 42)), 0.0
    else:
        cost = meter.charge("imagen_image", 1, "assets")
        data = _with_backoff(lambda: _imagen_image(prompt))
    data = _compose_thumbnail_text(data, project.title)
    _save_asset(project, "assets", None, "thumbnail", "thumbnail.png", data, cost,
                {"prompt": prompt, "text_composited": True})


def _compose_thumbnail_text(bg_bytes: bytes, title: str) -> bytes:
    """サムネイルにタイトル文字をプログラム合成する(AIに文字を描かせない)。"""
    from PIL import Image, ImageDraw

    from app.services.motion import _font

    img = Image.open(io.BytesIO(bg_bytes)).convert("RGB")
    img = img.resize((1280, max(720, int(img.height * 1280 / img.width))))
    img = img.crop((0, 0, 1280, 720))
    draw = ImageDraw.Draw(img)
    # タイトルを2行までに整形
    lines = []
    buf = ""
    for ch in title:
        buf += ch
        if len(buf) >= 11:
            lines.append(buf)
            buf = ""
        if len(lines) == 2:
            break
    if buf and len(lines) < 2:
        lines.append(buf)
    font = _font(96)
    y = 720 - 110 * len(lines) - 60
    for line in lines:
        draw.text((56, y), line, font=font, fill=(255, 255, 255),
                  stroke_width=8, stroke_fill=(10, 12, 20))
        y += 110
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def generate_all(project: Project) -> None:
    """全シーンの素材を生成。採用済み素材はスキップ(再開・部分再生成に対応)。

    CostLimitExceeded は呼び出し側で処理する(案件は素材生成中のまま停止)。
    """
    meter = CostMeter(project)
    for scene in project.scenes:
        visual_kind = "video" if (scene.type == "ai_video" and not settings.is_local) else "image"
        if not find_asset(project, "assets", scene.no, visual_kind):
            _gen_visual(project, scene, meter)
        if not find_asset(project, "assets", scene.no, "narration"):
            _gen_narration(project, scene, meter)
    if not find_asset(project, "assets", None, "bgm"):
        _gen_bgm(project, meter)
    if not find_asset(project, "assets", None, "thumbnail"):
        _gen_thumbnail(project, meter)
    project.cost_stop_reason = ""
    project.log("素材生成完了", note=f"累計費用 ¥{project.total_cost()}")
