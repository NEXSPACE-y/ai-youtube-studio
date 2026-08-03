"""V2-A: 原画の鎖の形(星型 vs 直列)を実測する。

プロトコル: docs/10_V2検証プロトコル.md §2(実施前に確定済み)
  星型   canon → S1, canon → S2, canon → S3   (すべて世代1)
  直列   canon → D1, D1 → D2, D2 → D3         (世代1/2/3)
生成指示は全条件で同一。構図を固定し、差がキャラのドリフトのみに帰属するようにする。
"""
import os
import sys
from pathlib import Path

OUT = Path("/private/tmp/claude-501/-Users-yoshiki-Desktop-ai-youtube-studio/"
           "2da98fea-9ca3-4b84-9873-0c446d96375b/scratchpad/v2a")
ROOT = Path.home() / "Desktop/ai-youtube-studio"
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from google import genai
from google.genai import types

MODEL = os.environ.get("IMAGEN_MODEL", "gemini-2.5-flash-image")
client = genai.Client(vertexai=True, project=os.environ["GCP_PROJECT"],
                      location=os.environ.get("MEDIA_REGION", "us-central1"))

# 全条件で同一の「照合カット」指示。構図・背景・画角をすべて固定する
PROMPT = (
    "Redraw the character from this image as a full-body standing pose, facing "
    "the viewer straight on, arms relaxed at her sides, neutral closed-mouth "
    "expression. Plain flat cream background, no scenery, no props, no shadow "
    "other than a simple ellipse under the feet. Centered, full body visible, "
    "same distance from the camera. "
    "Keep the character design EXACTLY as in the input image: the same face, "
    "the same round glasses, the same hairstyle and hair color, the same grey "
    "cardigan, white collared shirt, dark trousers and brown boots, the same "
    "flat 2D anime line-art style and the same colors. "
    "Do not add text, letters or logos."
)


def generate(src: Path, dst: Path) -> None:
    part = types.Part.from_bytes(data=src.read_bytes(), mime_type="image/png")
    resp = client.models.generate_content(
        model=MODEL, contents=[part, PROMPT],
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]))
    for cand in resp.candidates or []:
        for p in cand.content.parts or []:
            blob = getattr(p, "inline_data", None)
            if blob and blob.data:
                dst.write_bytes(blob.data)
                print(f"  {src.name} -> {dst.name} ({len(blob.data)//1024}KB)")
                return
    raise RuntimeError(f"画像が返らなかった: {dst.name}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    canon = ROOT / "docs/characters/host_deform_sd.png"

    print("星型(すべて正史から直接):")
    for i in (1, 2, 3):
        generate(canon, OUT / f"S{i}.png")

    print("直列(前の世代から派生):")
    prev = canon
    for i in (1, 2, 3):
        dst = OUT / f"D{i}.png"
        generate(prev, dst)
        prev = dst

    print(f"\n完了。imagen_image × 6(コスト表基準 ¥36)")


main()
