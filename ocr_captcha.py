#!/usr/bin/env python3
"""识别 captcha.png 中的英文字母验证码。

多预处理 × 新旧模型，只统计 4 位结果，按字符位投票。
白边帮助漏字/a·e；raw/sat 对 b·k、a·d 更稳；中值滤波补漏首字。
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from io import BytesIO
from pathlib import Path

import ddddocr
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "captcha_model"
CUSTOM_ONNX = MODEL_DIR / "model.onnx"
CUSTOM_CHARSETS = MODEL_DIR / "charsets.json"

_ENGINES: list[tuple[str, ddddocr.DdddOcr]] | None = None
_CUSTOM: ddddocr.DdddOcr | None | bool = False  # False=未探测, None=无, else=引擎

_LETTER_RANGE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _custom_engine() -> ddddocr.DdddOcr | None:
    """若 captcha_model/ 下有专训 onnx，优先使用。"""
    global _CUSTOM
    if _CUSTOM is False:
        if CUSTOM_ONNX.is_file() and CUSTOM_CHARSETS.is_file():
            try:
                _CUSTOM = ddddocr.DdddOcr(
                    show_ad=False,
                    import_onnx_path=str(CUSTOM_ONNX),
                    charsets_path=str(CUSTOM_CHARSETS),
                )
                print(f"OCR 使用专训模型 {CUSTOM_ONNX.name}")
            except Exception as exc:
                print(f"专训模型加载失败，回退通用模型：{exc}")
                _CUSTOM = None
        else:
            _CUSTOM = None
    return _CUSTOM if _CUSTOM is not False else None


def _engines() -> list[tuple[str, ddddocr.DdddOcr]]:
    global _ENGINES
    if _ENGINES is None:
        _ENGINES = []
        for name, beta in (("beta", True), ("old", False)):
            eng = ddddocr.DdddOcr(show_ad=False, beta=beta)
            eng.set_ranges(_LETTER_RANGE)
            _ENGINES.append((name, eng))
    return _ENGINES


def _to_png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _flatten(data: bytes) -> Image.Image:
    im = Image.open(BytesIO(data)).convert("RGBA")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bg.paste(im, mask=im.split()[-1])
    return bg


def _pad(img: Image.Image, n: int) -> Image.Image:
    out = Image.new("RGB", (img.width + 2 * n, img.height + 2 * n), (255, 255, 255))
    out.paste(img, (n, n))
    return out


def _variants(data: bytes) -> list[tuple[str, bytes, float]]:
    """(name, png_bytes, weight)。无白边略提高权，pad12 降权避免带偏。"""
    bg = _flatten(data)
    out: list[tuple[str, bytes, float]] = []
    configs = (
        (0, "", 1.2),
        (8, "p8", 0.9),
        (12, "p12", 0.45),
    )
    for n, tag, pad_w in configs:
        base = bg if n == 0 else _pad(bg, n)
        up2 = base.resize(
            (base.width * 2, base.height * 2), Image.Resampling.LANCZOS
        )
        med = base.filter(ImageFilter.MedianFilter(3))
        arr = np.asarray(base)
        sat = arr.max(axis=2) - arr.min(axis=2)
        clean = Image.fromarray(
            np.where((sat > 25)[..., None], arr, 255).astype(np.uint8)
        )
        dist = np.linalg.norm(255 - arr.astype(np.float32), axis=2)
        dist_img = Image.fromarray(
            np.where((dist > 40)[..., None], arr, 255).astype(np.uint8)
        )
        items: list[tuple[str, Image.Image, float]] = [
            ("raw", base, 1.8 * pad_w),
            ("auto", ImageOps.autocontrast(base), 1.6 * pad_w),
            ("sat25", clean, 1.8 * pad_w),
            ("dist40", dist_img, 1.5 * pad_w),
            ("c15", ImageEnhance.Contrast(base).enhance(1.5), 0.9 * pad_w),
            ("c20", ImageEnhance.Contrast(base).enhance(2.0), 0.8 * pad_w),
            ("c15u", ImageEnhance.Contrast(up2).enhance(1.5), 0.9 * pad_w),
            ("c20u", ImageEnhance.Contrast(up2).enhance(2.0), 0.8 * pad_w),
            ("medc2", ImageEnhance.Contrast(med).enhance(2.0), 1.6 * pad_w),
            ("medc25", ImageEnhance.Contrast(med).enhance(2.5), 1.3 * pad_w),
        ]
        for name, img, vw in items:
            key = f"{tag}{name}" if tag else name
            out.append((key, _to_png_bytes(img), vw))
    return out


def _normalize(text: str) -> str:
    return "".join(c for c in (text or "") if c.isalpha()).lower()


def _vote(data: bytes) -> tuple[str, list[tuple[str, float]]]:
    str_score: dict[str, float] = defaultdict(float)
    char_votes: list[dict[str, float]] = [defaultdict(float) for _ in range(4)]

    for eng_name, eng in _engines():
        for _vname, vdata, vw in _variants(data):
            try:
                text = _normalize(eng.classification(vdata))
            except Exception:
                continue
            # 本站验证码固定 4 位，短结果不参与决策
            if len(text) != 4:
                continue
            w = float(vw)
            if eng_name == "old":
                w += 0.1
            str_score[text] += w
            for i, ch in enumerate(text):
                char_votes[i][ch] += w

    ranked = sorted(str_score.items(), key=lambda x: (-x[1], x[0]))
    if not ranked:
        return "", []

    consensus = ""
    if all(char_votes[i] for i in range(4)):
        consensus = "".join(
            max(char_votes[i].items(), key=lambda x: x[1])[0] for i in range(4)
        )

    best_str, best_str_score = ranked[0]
    if consensus:
        cons_score = str_score.get(consensus, 0.0)
        # 字符位共识优先；仅当整串得分明显高于共识串时才改用整串
        if best_str != consensus and best_str_score > cons_score * 1.35:
            best = best_str
        else:
            best = consensus
    else:
        best = best_str

    # 把共识也放进榜里方便 debug
    if consensus and consensus not in str_score:
        ranked = [(consensus, str_score.get(consensus, 0.0))] + ranked
    return best, ranked


def recognize(image_path: Path | str) -> str:
    data = Path(image_path).read_bytes()
    custom = _custom_engine()
    if custom is not None:
        try:
            text = _normalize(custom.classification(data))
            if len(text) >= 3:
                return text.upper()
        except Exception:
            pass
    best, _ = _vote(data)
    return best.upper()


def recognize_debug(image_path: Path | str) -> tuple[str, list[tuple[str, float]]]:
    data = Path(image_path).read_bytes()
    custom = _custom_engine()
    if custom is not None:
        try:
            text = _normalize(custom.classification(data))
            print(f"  custom model -> {text}")
        except Exception as exc:
            print(f"  custom model error: {exc}")
    for eng_name, eng in _engines():
        for vname, vdata, _vw in _variants(data):
            try:
                text = _normalize(eng.classification(vdata))
            except Exception:
                continue
            if text:
                print(f"  {eng_name:4s} {vname:12s} -> {text}")
    best, ranked = _vote(data)
    return best.upper(), [(t.upper(), s) for t, s in ranked]


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR 识别验证码图片")
    parser.add_argument(
        "image",
        nargs="?",
        default=str(ROOT / "captcha.png"),
        help="验证码图片路径（默认 captcha.png）",
    )
    parser.add_argument("--expect", default="", help="期望答案，对照是否一致")
    parser.add_argument("--debug", action="store_true", help="打印各变体识别与得分")
    args = parser.parse_args()

    path = Path(args.image)
    if not path.is_file():
        raise SystemExit(f"图片不存在: {path}")

    if args.debug:
        result, ranked = recognize_debug(path)
        print("得分:", ", ".join(f"{t}={s:.1f}" for t, s in ranked[:6]))
    else:
        result = recognize(path)
    print(result)

    if args.expect:
        expect = "".join(c for c in args.expect if c.isalpha()).upper()
        ok = result == expect
        print(f"期望: {expect}  匹配: {'OK' if ok else 'FAIL'}")
        raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
