#!/usr/bin/env python3
"""把已标注验证码整理成 dddd_trainer 可用的训练集。

数据来源
  - captcha_wrong/*_{ocr}__{正确}.png   ← 你手动标的错例（双下划线后是正确答案）
  - captcha_ok/*_{正确}.png             ← 提交成功自动留下的（答案=当时 OCR）

导出格式（文件名导入）
  captcha_data/images/{label}_{hash}.png

统计
  python prepare_captcha_dataset.py
  python prepare_captcha_dataset.py --export

专训步骤（样本建议 ≥300，越好 ≥800）
  1. git clone https://github.com/sml2h3/dddd_trainer.git
  2. cd dddd_trainer && pip install -r requirements.txt
  3. python app.py create jifen_captcha
  4. python app.py cache jifen_captcha /path/to/jifen/captcha_data
  5. 按需改 projects/jifen_captcha/config.yaml（CPU 可设 GPU: false）
  6. python app.py train jifen_captcha
  7. 把生成的 .onnx + charsets.json 拷到本仓库 captcha_model/
     命名为 model.onnx / charsets.json
  8. 重启 bot；ocr_captcha 会优先加载自定义模型
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WRONG = ROOT / "captcha_wrong"
OK = ROOT / "captcha_ok"
OUT = ROOT / "captcha_data"
OUT_IMAGES = OUT / "images"

# guess__truth.png
WRONG_PAT = re.compile(r"_([A-Za-z]+)__([A-Za-z]+)\.png$", re.I)
# stamp_label.png（成功样本）
OK_PAT = re.compile(r"_([A-Za-z]+)\.png$", re.I)


def _norm(label: str) -> str:
    return "".join(c for c in label if c.isalpha()).lower()


def collect_labeled() -> list[tuple[Path, str, str]]:
    """返回 (path, label, source)。"""
    rows: list[tuple[Path, str, str]] = []
    if WRONG.is_dir():
        for p in sorted(WRONG.glob("*.png")):
            m = WRONG_PAT.search(p.name)
            if not m:
                continue
            label = _norm(m.group(2))
            if len(label) >= 3:
                rows.append((p, label, "wrong"))
    if OK.is_dir():
        for p in sorted(OK.glob("*.png")):
            if "__" in p.name:
                continue
            m = OK_PAT.search(p.name)
            if not m:
                continue
            label = _norm(m.group(1))
            if len(label) >= 3:
                rows.append((p, label, "ok"))
    return rows


def summarize(rows: list[tuple[Path, str, str]]) -> None:
    by_src = Counter(s for _, _, s in rows)
    labels = Counter(lab for _, lab, _ in rows)
    print(f"已标注合计: {len(rows)}")
    print(f"  captcha_wrong(已标): {by_src.get('wrong', 0)}")
    print(f"  captcha_ok(成功):    {by_src.get('ok', 0)}")
    if not rows:
        print("还没有可用样本。错例请命名为: 时间_ocr猜__正确答案.png")
        return
    lens = Counter(len(lab) for _, lab, _ in rows)
    print(f"标签长度分布: {dict(sorted(lens.items()))}")
    print(f"不重复标签数: {len(labels)}")
    if len(rows) < 300:
        print(f"建议再攒到 ≥300 张再训（当前 {len(rows)}）。继续跑 --auto，成功的会进 captcha_ok/。")
    elif len(rows) < 800:
        print(f"已达起步量 {len(rows)}，可先试训；凑到 800+ 通常更稳。")
    else:
        print(f"样本较充足（{len(rows)}），可以开训。")


def export(rows: list[tuple[Path, str, str]]) -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT_IMAGES.mkdir(parents=True)
    n = 0
    for src, label, _ in rows:
        digest = hashlib.md5(src.read_bytes()).hexdigest()[:16]
        dest = OUT_IMAGES / f"{label}_{digest}.png"
        # 同内容只留一份
        if dest.exists():
            continue
        shutil.copy2(src, dest)
        n += 1
    # dddd_trainer 文件名模式要求图片直接在数据集目录下，或 images+labels。
    # 这里再平铺一份到 captcha_data/ 根目录（文件名导入更省事）。
    for p in OUT_IMAGES.glob("*.png"):
        flat = OUT / p.name
        if not flat.exists():
            shutil.copy2(p, flat)
    print(f"已导出 {n} 张 → {OUT}/ （可用 python app.py cache <项目> {OUT}）")
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description="统计/导出验证码训练数据")
    parser.add_argument(
        "--export",
        action="store_true",
        help="导出到 captcha_data/ 供 dddd_trainer 使用",
    )
    args = parser.parse_args()
    rows = collect_labeled()
    summarize(rows)
    if args.export:
        if not rows:
            raise SystemExit(1)
        export(rows)


if __name__ == "__main__":
    main()
