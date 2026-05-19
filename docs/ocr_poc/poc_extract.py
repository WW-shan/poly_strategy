#!/usr/bin/env python3
"""
OCR POC for #11 external fact signal pipeline
=============================================

最小可演示流程：
  SEC EDGAR API → 找一个含 PDF exhibit 的 8-K filing
  → 下载 PDF → pypdf 抽文本（text-layer PDFs）
  → 用 LLM 抽结构化 fact（POC 里只 stub，不真调 LLM）
  → 报告 text-only API 没拿到的 fact

跑法：
  cd ~/jz_code/poly_strategy
  .venv/bin/python docs/ocr_poc/poc_extract.py

输出：docs/ocr_poc/result_<timestamp>.md + cache/ 目录下的原始 PDF
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import requests
from pypdf import PdfReader

# SEC 要求带 User-Agent + email 标识自己
SEC_HEADERS = {
    "User-Agent": "OCR-POC research (jingheng_zhang@outlook.com)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov",
}

DOWNLOAD_HEADERS = {
    "User-Agent": "OCR-POC research (jingheng_zhang@outlook.com)",
    "Accept-Encoding": "gzip, deflate",
}

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
CACHE.mkdir(exist_ok=True)


def fetch_recent_8k(cik: str, max_filings: int = 20) -> list[dict]:
    """拉 N 个最近 filing 的元数据；筛 8-K"""
    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    r = requests.get(url, headers=SEC_HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()
    recent = data["filings"]["recent"]
    rows = []
    for i in range(min(max_filings, len(recent["accessionNumber"]))):
        form = recent["form"][i]
        if form != "8-K":
            continue
        rows.append({
            "accession": recent["accessionNumber"][i],
            "form": form,
            "filing_date": recent["filingDate"][i],
            "report_date": recent["reportDate"][i],
            "primary_doc": recent["primaryDocument"][i],
            "primary_doc_desc": recent["primaryDocDescription"][i],
        })
    return rows


def list_filing_attachments(cik: str, accession: str) -> list[dict]:
    """列出一个 filing 的所有附件文件（含 PDF）"""
    acc_nodash = accession.replace("-", "")
    cik_int = str(int(cik))
    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_int}&type=8-K&dateb=&owner=include&count=10&action=getcompany"
    # 简化：直接列出 EDGAR 文件夹索引
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/"
    r = requests.get(index_url, headers=DOWNLOAD_HEADERS, timeout=15)
    r.raise_for_status()
    html = r.text
    files = re.findall(r'href="([^"]+\.(?:pdf|htm|txt))"', html, re.IGNORECASE)
    files = sorted(set(files))
    out = []
    for f in files:
        if f.startswith("/"):
            url = f"https://www.sec.gov{f}"
        else:
            url = index_url + f
        out.append({"name": f.split("/")[-1], "url": url})
    return out


def download_pdf(url: str, dest: Path) -> Path:
    if dest.exists():
        return dest
    r = requests.get(url, headers=DOWNLOAD_HEADERS, timeout=30)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def extract_pdf_text(pdf_path: Path) -> dict:
    """抽取 PDF 文本 + 元数据。返回 {pages, text, has_text_layer, total_chars}"""
    try:
        reader = PdfReader(str(pdf_path))
        pages = len(reader.pages)
        text_parts = []
        for p in reader.pages:
            try:
                t = p.extract_text() or ""
                text_parts.append(t)
            except Exception as e:
                text_parts.append(f"[page extract error: {e}]")
        full = "\n\n".join(text_parts)
        has_layer = len(full.strip()) > 100  # 极少文本 = 大概率是 scan
        return {
            "pages": pages,
            "text": full,
            "has_text_layer": has_layer,
            "total_chars": len(full),
        }
    except Exception as e:
        return {"error": str(e), "pages": 0, "text": "", "has_text_layer": False, "total_chars": 0}


def stub_llm_fact_extraction(text: str, company: str, filing_date: str) -> dict:
    """
    POC 阶段不真 call LLM（避免 token 成本）。
    生产里这里会调 OpenRouter（gemini-flash + qwen fallback）按 spec 里 structured_fact 的 schema 抽取。
    POC 只做正则启发提取，证明 pipeline 通了。
    """
    excerpt = text[:1500]
    # 简单启发：找钱数、日期、事件关键词
    money_matches = re.findall(r"\$\s*[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand|M|B)?", excerpt, re.IGNORECASE)[:5]
    event_kw = re.findall(
        r"\b(acquir\w+|merger|settle\w*|fine\w*|charged|indict\w+|approv\w+|recall\w+|bankruptc\w+|investigat\w+|dividend|buyback)\b",
        excerpt, re.IGNORECASE,
    )[:5]
    return {
        "schema_version": 1,
        "company": company,
        "filing_date": filing_date,
        "_method": "regex_stub_for_poc",  # 标明这是占位
        "money_mentions": money_matches,
        "event_keywords": list(set(k.lower() for k in event_kw)),
        "first_1500_chars": excerpt,
    }


def test_known_pdf(url: str, label: str) -> dict:
    """直接用一个已知 PDF URL 验证 pypdf 抽取链路通。"""
    dest = CACHE / f"known_{label}.pdf"
    if not dest.exists():
        try:
            r = requests.get(url, headers=DOWNLOAD_HEADERS, timeout=30, allow_redirects=True)
            r.raise_for_status()
            dest.write_bytes(r.content)
        except Exception as e:
            return {"label": label, "url": url, "error": f"download failed: {e}"}
    ext = extract_pdf_text(dest)
    return {
        "label": label,
        "url": url,
        "size_bytes": dest.stat().st_size,
        "pages": ext["pages"],
        "total_chars": ext["total_chars"],
        "has_text_layer": ext["has_text_layer"],
        "first_300_chars": ext["text"][:300],
    }


# === Federal Register: source family spec 明确列的 ===

def fetch_fr_recent_docs(limit: int = 5, agency: str | None = None) -> list[dict]:
    """拉 Federal Register 最近 documents（spec 里 Federal Register 是 3 个核心 source 之一）"""
    params = ["per_page=" + str(limit)]
    if agency:
        params.append(f"conditions[agencies][]={agency}")
    url = "https://www.federalregister.gov/api/v1/documents.json?" + "&".join(params)
    r = requests.get(url, headers=DOWNLOAD_HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()
    return [
        {
            "doc_num": d["document_number"],
            "title": d["title"],
            "type": d["type"],
            "pub_date": d["publication_date"],
            "pdf_url": d["pdf_url"],
            "pi_pdf_url": d.get("public_inspection_pdf_url"),
            "agencies": [a["name"] for a in d.get("agencies", [])],
        }
        for d in data["results"]
    ]


def fetch_fr_pdf_with_fallback(doc: dict) -> dict:
    """先试 public-inspection（FR 直发），失败 fallback govinfo"""
    label = doc["doc_num"]
    dest = CACHE / f"fr_{label}.pdf"
    if dest.exists():
        return {"path": dest, "url_used": "(cached)"}

    candidates = [doc.get("pi_pdf_url"), doc.get("pdf_url")]
    for url in candidates:
        if not url:
            continue
        try:
            r = requests.get(url, headers=DOWNLOAD_HEADERS, timeout=30, allow_redirects=True)
            r.raise_for_status()
            dest.write_bytes(r.content)
            return {"path": dest, "url_used": url}
        except Exception:
            continue
    return {"error": "all PDF URLs failed", "tried": candidates}


def main():
    # 测试目标：Apple 最近的 8-K（频繁有 PDF exhibits）
    targets = [
        ("0000320193", "Apple Inc"),
        ("0001318605", "Tesla Inc"),
    ]

    results = []
    for cik, name in targets:
        print(f"\n=== {name} (CIK {cik}) ===")
        try:
            filings = fetch_recent_8k(cik, max_filings=30)
        except Exception as e:
            print(f"  ⚠️  无法拉 filing list: {e}")
            continue
        if not filings:
            print("  无 8-K")
            continue
        # 取最近一个 8-K
        f = filings[0]
        print(f"  最近 8-K: {f['filing_date']} {f['primary_doc']}")
        try:
            attachments = list_filing_attachments(cik, f["accession"])
        except Exception as e:
            print(f"  ⚠️  无法列 attachments: {e}")
            continue

        pdfs = [a for a in attachments if a["name"].lower().endswith(".pdf")]
        non_pdfs = [a for a in attachments if not a["name"].lower().endswith(".pdf")]
        print(f"  attachments: {len(attachments)} 个（{len(pdfs)} PDF + {len(non_pdfs)} 其他）")

        if not pdfs:
            results.append({
                "company": name,
                "cik": cik,
                "filing": f,
                "pdf_count": 0,
                "skipped_reason": "no_pdf_attachment",
                "attachments": [a["name"] for a in attachments],
            })
            continue

        pdf = pdfs[0]
        print(f"  下载 PDF: {pdf['name']} from {pdf['url']}")
        try:
            dest = download_pdf(pdf["url"], CACHE / f"{cik}_{f['accession']}_{pdf['name']}")
        except Exception as e:
            print(f"  ⚠️  下载失败: {e}")
            continue
        print(f"  存到: {dest} ({dest.stat().st_size:,} bytes)")
        extracted = extract_pdf_text(dest)
        print(f"  pages: {extracted['pages']}, chars: {extracted['total_chars']}, text_layer: {extracted['has_text_layer']}")

        fact = stub_llm_fact_extraction(extracted["text"], name, f["filing_date"])
        results.append({
            "company": name,
            "cik": cik,
            "filing": f,
            "attachments_summary": {
                "total": len(attachments),
                "pdf_count": len(pdfs),
                "other_count": len(non_pdfs),
                "first_pdf": pdf["name"],
            },
            "extraction": {
                "pages": extracted["pages"],
                "total_chars": extracted["total_chars"],
                "has_text_layer": extracted["has_text_layer"],
                "first_300_chars": extracted["text"][:300],
            },
            "stub_fact": fact,
        })

    # === Federal Register 真实 PDF 路径（spec 列的 source family）===
    print("\n=== Federal Register PDF 抽取 ===")
    fr_results = []
    try:
        fr_docs = fetch_fr_recent_docs(limit=3)
        for doc in fr_docs:
            print(f"  --- [{doc['type']}] {doc['title'][:80]}")
            print(f"      pub: {doc['pub_date']}  agency: {(doc['agencies'] or ['?'])[0]}")
            dl = fetch_fr_pdf_with_fallback(doc)
            if "error" in dl:
                print(f"      ⚠️  下载失败: {dl}")
                fr_results.append({"doc": doc, "error": dl})
                continue
            ext = extract_pdf_text(dl["path"])
            print(f"      ✅ pages={ext['pages']}  chars={ext['total_chars']}  text_layer={ext['has_text_layer']}")
            fact = stub_llm_fact_extraction(ext["text"], doc["agencies"][0] if doc["agencies"] else "FR", doc["pub_date"])
            fr_results.append({
                "doc": doc,
                "downloaded_from": dl["url_used"],
                "extraction": {
                    "pages": ext["pages"],
                    "total_chars": ext["total_chars"],
                    "has_text_layer": ext["has_text_layer"],
                    "first_300_chars": ext["text"][:300],
                },
                "stub_fact": fact,
            })
    except Exception as e:
        print(f"  ⚠️  FR API 异常: {e}")
        fr_results.append({"error": str(e)})

    # 写报告
    out = ROOT / f"result_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(
        {"sec_8k_scan": results, "federal_register_pdf_extraction": fr_results},
        ensure_ascii=False, indent=2,
    ))
    print(f"\n=== 写 {out} ===")
    return results, fr_results


if __name__ == "__main__":
    main()
