"""原画B生成: 原画Aと同一画角・同一背景で、姿勢だけ違うキーフレームを作る。

中割り(last_frame)の検証には「同じショットのA/Bペア」が要る。
K1〜K8は別カットなので、Aから編集してBを作る。
"""
import os
import sys
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

MODEL = os.environ.get("IMAGEN_MODEL", "gemini-2.5-flash-image")
# メディア系モデルは提供リージョンが限られる(config.py の media_region と同じ扱い)
client = genai.Client(vertexai=True, project=os.environ["GCP_PROJECT"],
                      location=os.environ.get("MEDIA_REGION", "us-central1"))

PROMPT = (
    "Edit this anime illustration. Keep EVERYTHING identical: the exact same "
    "character design, face, glasses, hairstyle, grey cardigan, the same library "
    "background, the same camera angle, the same framing, the same flat 2D anime "
    "line-art style, the same colors and lighting. "
    "Change ONLY the pose: lower her raised right hand down to her side so it is "
    "no longer visible, close her mouth into a gentle closed-mouth smile, and tilt "
    "her head very slightly to her left. "
    "Do not add or remove any object. Do not change the background. "
    "Do not add text, letters or logos. Output the full frame at the same aspect ratio."
)

img = types.Part.from_bytes(
    data=(SP / "exp/A_k2_16x9.png").read_bytes(), mime_type="image/png")

print(f"model={MODEL}  呼び出し中...")
resp = client.models.generate_content(
    model=MODEL,
    contents=[img, PROMPT],
    config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
)

saved = 0
for cand in resp.candidates or []:
    for part in cand.content.parts or []:
        blob = getattr(part, "inline_data", None)
        if blob and blob.data:
            out = SP / "exp/B_k2_pose.png"
            out.write_bytes(blob.data)
            print("原画B 保存:", out, len(blob.data), "bytes")
            saved += 1
        elif getattr(part, "text", None):
            print("[text]", part.text[:300])
if not saved:
    print("画像が返らなかった。finish_reason:",
          [getattr(c, "finish_reason", None) for c in (resp.candidates or [])])
    sys.exit(1)
