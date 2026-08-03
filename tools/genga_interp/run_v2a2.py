"""V2-A2: 交絡を除いた鎖の形の比較。プロトコル docs/12(実施前に確定済み)。"""
import os
from pathlib import Path

OUT = Path("/private/tmp/claude-501/-Users-yoshiki-Desktop-ai-youtube-studio/"
           "2da98fea-9ca3-4b84-9873-0c446d96375b/scratchpad/v2a2")
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

KEEP = ("Keep the character design EXACTLY as in the input image: the same face, "
        "the same round glasses, the same hairstyle and hair color, the same grey "
        "cardigan, white collared shirt, dark trousers and brown boots, the same "
        "flat 2D anime line-art style and the same colors. "
        "Do not add text, letters or logos.")

CUTS = {
    "C1": ("Redraw this character seated at a large wooden desk reading an open "
           "book, seen from a wide shot inside an archive room with card catalog "
           "cabinets behind her. " + KEEP),
    "C2": ("Redraw this character standing in front of tall bookshelves, raising "
           "one hand, seen as a medium shot. " + KEEP),
    "C3": ("Redraw this character standing by an arched window looking outside, "
           "seen in profile as a close shot. " + KEEP),
}
NORMALIZE = (
    "Redraw the character from this image as a full-body standing pose, facing "
    "the viewer straight on, arms relaxed at her sides, neutral closed-mouth "
    "expression. Plain flat cream background, no scenery, no props. Centered, "
    "full body visible. " + KEEP)


import sys
import time

sys.path.insert(0, str(ROOT))
from app.services.media import _with_backoff  # 429の自動リトライ(15→30→60→120秒)


def gen(src: Path, dst: Path, prompt: str) -> Path:
    if dst.exists():  # 中断からの再開。既に取れている結果は引き直さない
        print(f"  {src.name:>14} -> {dst.name} (既存・スキップ)")
        return dst

    def _once():
        part = types.Part.from_bytes(data=src.read_bytes(), mime_type="image/png")
        resp = client.models.generate_content(
            model=MODEL, contents=[part, prompt],
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]))
        for c in resp.candidates or []:
            for p in c.content.parts or []:
                b = getattr(p, "inline_data", None)
                if b and b.data:
                    return b.data
        raise RuntimeError(f"画像が返らなかった: {dst.name}")

    dst.write_bytes(_with_backoff(_once, attempts=6, base_wait=20.0))
    print(f"  {src.name:>14} -> {dst.name}")
    time.sleep(8)  # レート制限に当たりにくくする
    return dst


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    canon = ROOT / "docs/characters/host_deform_sd.png"

    print("星型(すべて正史から):")
    A = [gen(canon, OUT / f"A{i}.png", CUTS[f"C{i}"]) for i in (1, 2, 3)]

    print("直列(前のカットから):")
    B, prev = [], canon
    for i in (1, 2, 3):
        prev = gen(prev, OUT / f"B{i}.png", CUTS[f"C{i}"])
        B.append(prev)

    print("照合カット(共通の最終変換):")
    for src in A + B:
        gen(src, OUT / f"N{src.stem}.png", NORMALIZE)

    print("挙動プローブP1(B1に大きな変換を2回):")
    for k in (1, 2):
        gen(B[0], OUT / f"P1_{k}.png", CUTS["C3"])

    print("\n完了。imagen_image × 14(コスト表基準 ¥84)")


main()
