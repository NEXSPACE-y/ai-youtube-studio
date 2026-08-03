"""原画の一貫性を機械的に測る(docs/10 のV2-B)。

主観で「崩れた」と言うと再現できないため、2指標を数値で出す。
外部依存を増やさないためPillowのみで実装する(numpy等を要求しない)。

指標:
  mae   平均絶対差。0-255スケール。構図を固定した条件下では、値が大きいほど
        キャラの見た目が離れている
  hist  64ビン色ヒストグラムのL1距離をチャンネル平均し 0-1 に正規化したもの。
        位置ずれに鈍く、色・パレットの変化に敏感

2指標を併記するのは、片方だけでは判断を誤るため(構図が僅かにずれるとmaeは
跳ねるが、パレットが同じならhistは動かない)。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

SIZE = (512, 512)  # 比較前に揃える


def _load(path: str | Path) -> Image.Image:
    return Image.open(path).convert("RGB").resize(SIZE, Image.LANCZOS)


def mae(a: Image.Image, b: Image.Image) -> float:
    """平均絶対差(0-255)。全チャンネル平均。"""
    diff = ImageChops.difference(a, b)
    return sum(ImageStat.Stat(diff).mean) / 3


def hist_distance(a: Image.Image, b: Image.Image, bins: int = 64) -> float:
    """正規化ヒストグラムのL1距離(0-1)。0が一致。"""
    step = 256 // bins
    total = 0.0
    for ch in range(3):
        ha = a.getchannel(ch).histogram()
        hb = b.getchannel(ch).histogram()
        n = float(SIZE[0] * SIZE[1])
        for i in range(bins):
            pa = sum(ha[i * step:(i + 1) * step]) / n
            pb = sum(hb[i * step:(i + 1) * step]) / n
            total += abs(pa - pb)
    return total / 6  # 3ch × L1最大2 → 0-1に正規化


def compare(ref_path: str | Path, target_path: str | Path) -> dict:
    a, b = _load(ref_path), _load(target_path)
    return {"mae": round(mae(a, b), 3), "hist": round(hist_distance(a, b), 4)}


if __name__ == "__main__":
    ref = sys.argv[1]
    print(f"{'target':<28} {'mae':>8} {'hist':>8}")
    for t in sys.argv[2:]:
        m = compare(ref, t)
        print(f"{Path(t).name:<28} {m['mae']:>8.3f} {m['hist']:>8.4f}")
