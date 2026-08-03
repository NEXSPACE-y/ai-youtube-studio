"""検証用動画ビルド(ステップ0 / API呼び出しなし・費用ゼロ)。

既存の原画8枚 + 既存TTS2本のみで40秒を組む。
ツヅリはK5の飛翔ポーズを活かし、消えていたネジ巻きキーをプログラムで合成済み。
"""
import subprocess
import wave
from pathlib import Path

from PIL import Image

BASE = Path(__file__).parent
CUTS = BASE / "cuts"
OUT = BASE / "out"
OUT.mkdir(exist_ok=True)

W, H, FPS = 1280, 720, 30
UP = 1500  # 原画をこのサイズに上げてから窓を切る(パン・ズームの余白)

# (ファイル, 尺, 開始窓, 終了窓) 窓 = (中心x, 中心y, 幅) すべて UP 基準の正規化座標 0..1
CUTS_SPEC = [
    ("K1.png",       4.5, (0.50, 0.52, 1.00), (0.44, 0.46, 0.72)),  # 資料室・寄っていく
    ("K2.png",       4.0, (0.50, 0.48, 0.90), (0.50, 0.44, 0.70)),  # 栞に寄る
    ("K3.png",       6.0, (0.50, 0.50, 0.72), (0.50, 0.52, 1.00)),  # 工房・引いていく
    ("K4.png",       6.0, (0.52, 0.50, 1.00), (0.46, 0.46, 0.74)),  # 指差しに寄る
    ("K5_keyed.png", 5.0, (0.62, 0.34, 0.80), (0.38, 0.42, 0.80)),  # 空をパン(ツヅリ)
    ("K6.png",       4.5, (0.50, 0.50, 1.00), (0.50, 0.48, 0.78)),  # ツーショット
    ("K7.png",       4.0, (0.50, 0.48, 0.86), (0.50, 0.48, 0.66)),  # 機影
    ("K8.png",       4.0, (0.50, 0.50, 0.76), (0.50, 0.50, 1.00)),  # ラスト・引き
]

NARRATION = [  # (wav, 開始秒)
    (Path.home() / "Desktop/ai-youtube-studio/docs/characters/tts_shisho_Despina.wav", 0.3),
    (Path.home() / "Desktop/ai-youtube-studio/docs/characters/tts_toraji_Orus.wav", 8.9),
]


def ease(t):
    return t * t * (3 - 2 * t)  # smoothstep


def frames(path: Path, dur: float, a, b):
    src = Image.open(path).convert("RGB").resize((UP, UP), Image.LANCZOS)
    n = int(dur * FPS)
    for i in range(n):
        t = ease(i / max(1, n - 1))
        cx = a[0] + (b[0] - a[0]) * t
        cy = a[1] + (b[1] - a[1]) * t
        fw = a[2] + (b[2] - a[2]) * t
        w = fw * UP
        h = w * H / W
        x0 = cx * UP - w / 2
        y0 = cy * UP - h / 2
        x0 = max(0, min(UP - w, x0))
        y0 = max(0, min(UP - h, y0))
        win = src.crop((int(x0), int(y0), int(x0 + w), int(y0 + h)))
        yield win.resize((W, H), Image.BILINEAR).tobytes()


def build_clip(name, path, dur, a, b):
    out = OUT / f"clip_{name}.mp4"
    fade = f"fade=t=in:st=0:d=0.3,fade=t=out:st={dur - 0.3:.2f}:d=0.3,format=yuv420p"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "pipe:0", "-vf", fade, "-c:v", "libx264", "-preset", "medium",
           "-crf", "20", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in frames(path, dur, a, b):
        p.stdin.write(f)
    p.stdin.close()
    assert p.wait() == 0, f"ffmpeg failed on {name}"
    return out


def build_audio(total: float) -> Path:
    rate = 24000
    buf = bytearray(int(total * rate) * 2)
    for wav_path, start in NARRATION:
        with wave.open(str(wav_path), "rb") as w:
            assert w.getframerate() == rate and w.getnchannels() == 1
            data = w.readframes(w.getnframes())
        off = int(start * rate) * 2
        buf[off:off + len(data)] = data
    out = OUT / "audio.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(buf))
    return out


def main():
    total = sum(c[1] for c in CUTS_SPEC)
    clips = []
    for i, (f, dur, a, b) in enumerate(CUTS_SPEC, 1):
        clips.append(build_clip(f"{i:02d}", CUTS / f, dur, a, b))
        print(f"  cut {i}/8 {f} {dur}s")
    (OUT / "list.txt").write_text("".join(f"file '{c.name}'\n" for c in clips))
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "concat", "-safe", "0", "-i", "list.txt",
                    "-c", "copy", "base.mp4"], cwd=OUT, check=True)
    audio = build_audio(total)
    final = OUT / "testfilm_s1_dryrun.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", "base.mp4", "-i", audio.name,
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest",
                    final.name], cwd=OUT, check=True)
    print("done:", final, f"({total}s)")


main()
