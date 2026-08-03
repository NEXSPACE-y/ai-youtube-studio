"""中割り検証: 原画A→原画B の間を Veo に生成させる(docs/06 の中核仮説)。

安全策:
 - 既定は veo-3.1-lite(最安)。モデルはCLI引数で切替
 - generate_audio=False(音声はTTSが担当。動画のみの方が安い)
 - 失敗時はパラメータを落として再試行せず、そのまま報告する(想定外の課金を避ける)
"""
import os
import sys
import time
from pathlib import Path

SP = Path("/private/tmp/claude-501/-Users-yoshiki-Desktop-ai-youtube-studio/"
          "2da98fea-9ca3-4b84-9873-0c446d96375b/scratchpad")
ROOT = Path.home() / "Desktop/ai-youtube-studio"
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from google import genai
from google.genai import types

MODEL = sys.argv[1] if len(sys.argv) > 1 else "veo-3.1-lite-generate-001"
SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 8
OUT = SP / f"exp/interp_{MODEL.replace('.', '_')}_{SECONDS}s.mp4"

PROMPT = (
    "Flat 2D anime cel animation, limited animation style. A young librarian "
    "smoothly lowers her raised hand down to her side and closes her mouth into "
    "a gentle smile. The camera does not move. The background stays completely "
    "static. Consistent line art, consistent colors, no style change."
)
NEGATIVE = ("text, letters, subtitles, watermark, logo, extra characters, "
            "camera shake, zoom, style change, 3d render, photorealistic")

client = genai.Client(vertexai=True, project=os.environ["GCP_PROJECT"],
                      location=os.environ.get("MEDIA_REGION", "us-central1"))

first = types.Image(image_bytes=(SP / "exp/A_k2_16x9.png").read_bytes(),
                    mime_type="image/png")
last = types.Image(image_bytes=(SP / "exp/B_k2_16x9.png").read_bytes(),
                   mime_type="image/png")

cfg = types.GenerateVideosConfig(
    aspect_ratio="16:9",
    duration_seconds=SECONDS,
    last_frame=last,
    seed=20260803,
    negative_prompt=NEGATIVE,
    generate_audio=False,
    number_of_videos=1,
)

print(f"model={MODEL} seconds={SECONDS} last_frame=ON generate_audio=OFF")
print("送信中...")
op = client.models.generate_videos(model=MODEL, prompt=PROMPT, image=first, config=cfg)
t0 = time.time()
while not op.done:
    time.sleep(10)
    op = client.operations.get(op)
    print(f"  ...{time.time()-t0:.0f}s")
if getattr(op, "error", None):
    print("FAILED:", op.error)
    sys.exit(1)
vids = op.response.generated_videos
OUT.write_bytes(vids[0].video.video_bytes)
print(f"OK: {OUT} ({OUT.stat().st_size/1024/1024:.1f}MB / {time.time()-t0:.0f}秒で生成)")
