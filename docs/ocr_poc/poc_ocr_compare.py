#!/usr/bin/env python3
"""
OCR 对比 POC — 证明 pypdf 在 scan-only PDF 上失败、tesseract 救回来

方法：
  1. 取一份已下载的 Federal Register PDF（有 text layer，ground truth 已知）
  2. 把它**栅格化**成 image-only PDF（模拟 scan 输入）
  3. pypdf 抽 scan-only PDF —— 期望 fail / garbage
  4. tesseract OCR 同份 scan-only —— 期望恢复
  5. 跟 ground truth 比对字符级 / 关键词级 recall
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

from pdf2image import convert_from_path
from PIL import Image
from pypdf import PdfReader
import pytesseract

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"


def extract_via_pypdf(pdf_path: Path) -> str:
    """pypdf 直抽"""
    reader = PdfReader(str(pdf_path))
    return "\n".join(p.extract_text() or "" for p in reader.pages)


def rasterize_to_image_pdf(src: Path, dst: Path, dpi: int = 200) -> None:
    """把 text-layer PDF 栅格化为 image-only PDF（模拟扫描件）"""
    imgs = convert_from_path(str(src), dpi=dpi)
    # 转 RGB 后合并为多页 PDF（无 text layer）
    rgb_imgs = [img.convert("RGB") for img in imgs]
    rgb_imgs[0].save(str(dst), save_all=True, append_images=rgb_imgs[1:], format="PDF")


def ocr_via_tesseract(pdf_path: Path, dpi: int = 300) -> str:
    """pdf2image → 每页 tesseract OCR"""
    imgs = convert_from_path(str(pdf_path), dpi=dpi)
    return "\n".join(pytesseract.image_to_string(img, lang="eng") for img in imgs)


def normalize(text: str) -> set[str]:
    """字符串 → 词集合（去停用词、小写）"""
    words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
    return set(words)


def compare(ground_truth: str, candidate: str) -> dict:
    """词级 recall + char count + 第一段"""
    gt = normalize(ground_truth)
    ct = normalize(candidate)
    if not gt:
        return {"recall": 0.0, "intersect": 0, "gt_words": 0, "candidate_chars": len(candidate)}
    return {
        "recall": round(len(gt & ct) / len(gt), 3),
        "intersect": len(gt & ct),
        "gt_words": len(gt),
        "candidate_words": len(ct),
        "candidate_chars": len(candidate),
    }


def main():
    # 找一个已下载的 FR PDF
    fr_pdfs = sorted(CACHE.glob("fr_*.pdf"))
    if not fr_pdfs:
        print("⚠️  cache/ 下没找到 fr_*.pdf，请先跑 poc_extract.py")
        return
    src = fr_pdfs[0]
    print(f"使用源文件：{src.name}")

    # 1. ground truth
    gt_text = extract_via_pypdf(src)
    print(f"  ground truth: {len(gt_text)} chars, {len(normalize(gt_text))} 独立词")

    # 2. 栅格化成 scan-only
    scan_pdf = CACHE / src.name.replace("fr_", "scan_")
    print(f"\n栅格化 → {scan_pdf.name}（200 DPI）...")
    rasterize_to_image_pdf(src, scan_pdf, dpi=200)
    print(f"  scan-only PDF: {scan_pdf.stat().st_size:,} bytes")

    # 3. pypdf 抽 scan-only
    pypdf_text = extract_via_pypdf(scan_pdf)
    pypdf_vs_gt = compare(gt_text, pypdf_text)
    print(f"\n[pypdf on scan-only]")
    print(f"  chars: {len(pypdf_text)}  recall vs ground truth: {pypdf_vs_gt['recall']:.1%}")
    print(f"  首 80 字: {pypdf_text[:80]!r}")

    # 4. tesseract OCR
    print(f"\n[tesseract OCR on scan-only @ 300 DPI]")
    ocr_text = ocr_via_tesseract(scan_pdf, dpi=300)
    ocr_vs_gt = compare(gt_text, ocr_text)
    print(f"  chars: {len(ocr_text)}  recall vs ground truth: {ocr_vs_gt['recall']:.1%}")
    print(f"  首 200 字: {ocr_text[:200]!r}")

    # 5. 输出 JSON 报告
    result = {
        "source_pdf": src.name,
        "ground_truth": {"chars": len(gt_text), "words": len(normalize(gt_text))},
        "scan_only_pdf": scan_pdf.name,
        "pypdf_on_scan_only": {
            "chars": len(pypdf_text),
            "recall_vs_gt": pypdf_vs_gt,
            "first_200_chars": pypdf_text[:200],
        },
        "tesseract_on_scan_only": {
            "chars": len(ocr_text),
            "recall_vs_gt": ocr_vs_gt,
            "first_200_chars": ocr_text[:200],
        },
    }
    out = ROOT / "ocr_compare_result.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n=== 写 {out} ===")

    # 给个一句话裁决
    print("\n--- 裁决 ---")
    pypdf_recall = pypdf_vs_gt["recall"]
    ocr_recall = ocr_vs_gt["recall"]
    print(f"  pypdf 在 scan-only PDF 上 recall {pypdf_recall:.0%} → " + ("✗ FAIL" if pypdf_recall < 0.1 else "✓ ok"))
    print(f"  tesseract OCR 在同份上 recall {ocr_recall:.0%} → " + ("✓ rescued" if ocr_recall > 0.7 else "⚠️  partial" if ocr_recall > 0.3 else "✗ FAIL"))
    if pypdf_recall < 0.1 and ocr_recall > 0.7:
        print("\n  → OCR layer 在 scan-only 类源上**证实有价值**")


if __name__ == "__main__":
    main()
