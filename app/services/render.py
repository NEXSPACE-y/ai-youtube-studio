"""動画編集・合成(要件5.6)。ffmpegで映像/音声/BGM/字幕を統合する。

ffmpegが無い環境(ローカル動作確認など)では、全シーンを確認できる
HTMLプレビューを生成して工程を通す。本番コンテナにはffmpegを同梱。
"""

from __future__ import annotations

import html
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.models import Asset, Project
from app.services import motion, subtitles
from app.services.media import _save_asset, find_asset
from app.storage import get_storage

BGM_VOLUME = 0.22


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def run(project: Project) -> Asset:
    # 演出プラン未付与の案件(図解エンジン導入前)にはここで付与する
    if project.scenes and not any(motion.has_display(s.display) for s in project.scenes):
        from app.services import display

        display.plan(project)
    srt = subtitles.build_srt(project.scenes)
    _save_asset(project, "editing", None, "subtitle", "subtitles.srt",
                srt.encode("utf-8"), 0.0, {"lines": srt.count("-->")})
    if has_ffmpeg():
        asset = _render_ffmpeg(project, srt)
    else:
        asset = _render_preview_html(project, srt)
    project.log("編集(レンダリング)完了", note=asset.meta.get("format", ""))
    return asset


def _ff(args: list[str], cwd: Path) -> None:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                          cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg失敗: {proc.stderr[-800:]}")


def _pipe_clip(frames, wav_name: str, dur: float, out: str, tmp: Path) -> None:
    """モーションエンジンのフレーム列をffmpegへ直接流してクリップ化する。"""
    fade = (f"fade=t=in:st=0:d=0.35,"
            f"fade=t=out:st={max(0.0, dur - 0.35):.2f}:d=0.35,format=yuv420p")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1280x720", "-r", "30",
           "-i", "pipe:0", "-i", wav_name, "-t", f"{dur:.2f}", "-vf", fade,
           "-c:v", "libx264", "-preset", "veryfast",
           "-c:a", "aac", "-ar", "44100", "-shortest", out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, cwd=tmp)
    try:
        for frame in frames:
            proc.stdin.write(frame)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode("utf-8", errors="replace")
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg(モーション合成)失敗: {err[-800:]}")


_CJK_FONTS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
)


def _cjk_font() -> str:
    for f in _CJK_FONTS:
        if Path(f).exists():
            return f
    return ""


def _overlay_filter(tmp: Path, scene_no: int, text: str) -> str:
    """画面表示テキスト(テロップ)をffmpegで焼く。AIに文字を描かせない方針の要。"""
    font = _cjk_font()
    if not font or not text.strip():
        return ""
    tf = tmp / f"t{scene_no:03d}.txt"
    tf.write_text(text.strip(), encoding="utf-8")
    font_esc = font.replace("\\", "/").replace(":", r"\:")
    return (f",drawtext=textfile={tf.name}:fontfile='{font_esc}'"
            ":fontsize=42:fontcolor=white:borderw=2:bordercolor=black@0.6"
            ":box=1:boxcolor=black@0.45:boxborderw=18:x=48:y=44")


def _render_ffmpeg(project: Project, srt: str) -> Asset:
    storage = get_storage()
    # セクション先頭シーンに画面表示テキスト(台本のon_screen_text)をテロップ表示
    overlay_text: dict[int, str] = {}
    seen_sections: set[str] = set()
    section_text = {s.key: s.on_screen_text for s in project.script}
    for scene in project.scenes:
        if scene.section_key and scene.section_key not in seen_sections:
            seen_sections.add(scene.section_key)
            overlay_text[scene.no] = section_text.get(scene.section_key, "")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "subs.srt").write_text(srt, encoding="utf-8")
        clip_files = []
        for scene in project.scenes:
            narr = find_asset(project, "assets", scene.no, "narration")
            video = find_asset(project, "assets", scene.no, "video")
            image = find_asset(project, "assets", scene.no, "image")
            wav = tmp / f"n{scene.no:03d}.wav"
            wav.write_bytes(storage.read(narr.path))
            dur = scene.audio_duration_sec or scene.duration_sec
            out = f"clip{scene.no:03d}.mp4"
            overlay = _overlay_filter(tmp, scene.no, overlay_text.get(scene.no, ""))
            fade = (f",fade=t=in:st=0:d=0.35"
                    f",fade=t=out:st={max(0.0, dur - 0.35):.2f}:d=0.35")
            if motion.has_display(scene.display) and not video:
                # 図解モーションエンジン: 情報を運ぶ画面はプログラムが描く
                bg_bytes = storage.read(image.path) if image else None
                _pipe_clip(motion.render_frames(scene.display, bg_bytes, dur,
                                                seed=scene.no,
                                                section=scene.section_key),
                           wav.name, dur, out, tmp)
            elif video:
                src = tmp / f"v{scene.no:03d}.mp4"
                src.write_bytes(storage.read(video.path))
                vf = ("scale=1280:720:force_original_aspect_ratio=decrease,"
                      "pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p")
                _ff(["-stream_loop", "-1", "-i", src.name, "-i", wav.name,
                     "-t", f"{dur:.2f}", "-r", "30", "-vf", vf + overlay + fade,
                     "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
                     "-preset", "veryfast", "-c:a", "aac", "-ar", "44100", out], tmp)
            else:
                img = tmp / f"i{scene.no:03d}.png"
                img.write_bytes(storage.read(image.path))
                # 静止画にKen Burns風のズーム(要件3.2の簡易モーション)。奇数=寄り、偶数=引き
                frames = int(dur * 30) + 2
                zexpr = ("zoom+0.0008" if scene.no % 2
                         else "if(eq(on,1),1.22,zoom-0.0008)")
                vf = ("scale=2560:1440:force_original_aspect_ratio=increase,"
                      "crop=2560:1440,"
                      f"zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                      f":d={frames}:s=1280x720:fps=30,format=yuv420p")
                _ff(["-i", img.name, "-i", wav.name,
                     "-t", f"{dur:.2f}", "-vf", vf + overlay + fade,
                     "-c:v", "libx264", "-preset", "veryfast",
                     "-c:a", "aac", "-ar", "44100", "-shortest", out], tmp)
            clip_files.append(out)

        (tmp / "list.txt").write_text(
            "".join(f"file '{f}'\n" for f in clip_files), encoding="utf-8")
        _ff(["-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "base.mp4"], tmp)

        bgm_asset = find_asset(project, "assets", None, "bgm")
        bgm = tmp / "bgm.wav"
        bgm.write_bytes(storage.read(bgm_asset.path))
        _ff(["-i", "base.mp4", "-stream_loop", "-1", "-i", "bgm.wav",
             "-filter_complex",
             (f"[0:v]subtitles=subs.srt[v];[1:a]volume={BGM_VOLUME}[b];"
              "[0:a][b]amix=inputs=2:duration=first:dropout_transition=0[a]"),
             "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
             "-c:a", "aac", "final.mp4"], tmp)

        # Shorts自動切り出し(要件4章): 冒頭約40秒を縦型9:16に(ぼかし背景で上下埋め)
        _ff(["-i", "final.mp4", "-t", "40",
             "-filter_complex",
             ("[0:v]split[a][b];"
              "[a]scale=1080:1920:force_original_aspect_ratio=increase,"
              "crop=1080:1920,gblur=sigma=18[bg];"
              "[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2"),
             "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
             "short.mp4"], tmp)
        _save_asset(project, "editing", None, "short", "short.mp4",
                    (tmp / "short.mp4").read_bytes(), 0.0,
                    {"format": "mp4", "duration_sec": 40,
                     "note": "冒頭切り出しの縦型Shorts案"})

        data = (tmp / "final.mp4").read_bytes()
    total = round(sum(s.audio_duration_sec or s.duration_sec for s in project.scenes), 1)
    return _save_asset(project, "editing", None, "render", "final.mp4", data, 0.0,
                       {"format": "mp4", "duration_sec": total})


def _render_preview_html(project: Project, srt: str) -> Asset:
    storage = get_storage()
    total = round(sum(s.audio_duration_sec or s.duration_sec for s in project.scenes), 1)
    rows = []
    for scene in project.scenes:
        visual = (find_asset(project, "assets", scene.no, "video")
                  or find_asset(project, "assets", scene.no, "image"))
        narr = find_asset(project, "assets", scene.no, "narration")
        img_tag = (f'<img src="{storage.url_for(visual.path)}" alt="scene">'
                   if visual and visual.kind == "image"
                   else f'<video controls src="{storage.url_for(visual.path)}"></video>' if visual else "")
        subs = "<br>".join(html.escape(l) for l in subtitles.split_lines(scene.narration))
        rows.append(f"""
        <section>
          <h3>Scene {scene.no:02d} <small>[{scene.type} / {scene.audio_duration_sec or scene.duration_sec}秒]</small></h3>
          <div class="visual">{img_tag}</div>
          <p class="subs">{subs}</p>
          <audio controls src="{storage.url_for(narr.path) if narr else ''}"></audio>
        </section>""")
    doc = f"""<!doctype html><html lang="ja"><meta charset="utf-8">
<title>{html.escape(project.title)} 簡易プレビュー</title>
<style>
 body{{font-family:sans-serif;background:#111;color:#eee;max-width:900px;margin:0 auto;padding:16px}}
 section{{border:1px solid #333;border-radius:8px;padding:12px;margin:12px 0}}
 img,video{{max-width:100%;border-radius:4px}}
 .subs{{background:#000;padding:8px;border-radius:4px;color:#ffd}}
 .note{{color:#fa0}}
</style>
<h1>{html.escape(project.title)}</h1>
<p class="note">ffmpeg未検出のため簡易プレビューで代替(想定尺 {total}秒)。本番環境ではmp4を生成します。</p>
{''.join(rows)}
</html>"""
    return _save_asset(project, "editing", None, "render", "preview.html",
                       doc.encode("utf-8"), 0.0,
                       {"format": "html", "duration_sec": total,
                        "note": "ffmpeg未検出のため簡易プレビュー"})
