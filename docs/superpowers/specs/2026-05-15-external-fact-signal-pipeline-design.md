# External Fact Signal Pipeline Design

Date: 2026-05-15
Audience: PR discussion with Soli22de
Status: research/design spec, not an implementation plan yet

## Discussion Prompt for Soli22de

这次想讨论的不是继续做 maker/cross-platform arb，而是换成一个外部事实信号方向：

- 先从 Polymarket 的 active markets 和 resolution rules 出发，判断每个市场到底需要等什么外部事实。
- 再只盯少数可信来源，比如 SEC EDGAR、Federal Register、CourtListener 这类官方/API/RSS 来源。
- 新文档发布后，用 LLM 把非结构化内容抽成结构化事实。
- 再把事实映射回 market_id，产出现在项目已经能消费的 `external_signal`。
- 最后做 shadow report，看这个事实是否真的早于价格变化、扣掉 spread/depth 后还有没有可交易边际。

重点是不要做全网爬虫，也不要直接上交易。第一阶段要证明的是：这个管线能不能稳定找到“别人不容易结构化、但市场会关心”的新事实。

## Goal

Build a research pipeline that finds newly published, messy external facts and converts them into structured Polymarket signals.

The thesis is not "crawl more websites". The thesis is:

1. Start from live Polymarket markets and their resolution conditions.
2. Infer what external fact would actually resolve or materially move each market.
3. Watch trusted source families where those facts can appear first.
4. Use an LLM to turn raw/unstructured documents into structured facts.
5. Map facts back to market IDs and measure whether price moved after the fact appeared.

If this works, the edge comes from organizing unstructured public information faster and more consistently than other participants, not from generic arbitrage.

## Why This Exists

Recent research has weakened the pure maker/cross-platform arbitrage direction. Existing infrastructure can collect Polymarket markets, rules, order books, watchlists, external signal rows, realtime logs, and paper reports, but the current `external_signal` input is mostly a generic ingestion hook.

The next promising direction is an information pipeline:

- Market asks a question.
- The market's rules imply a trusted resolution source or fact type.
- A new external document is published.
- The LLM extracts the relevant fact into a strict schema.
- The system tests whether that fact arrived before a tradable price adjustment.

This should be implemented as shadow research first. No live trading is in scope.

## Current Repo Context

Useful existing pieces:

- `poly_strategy/external_signals.py` normalizes external scanner payloads into `external_signal` NDJSON.
- `poly_strategy/watchlist.py` boosts markets that appear in `external_signal` rows and keeps related neg-risk groups together.
- `scripts/refresh_external_signals.sh` can refresh `data/external-signals.ndjson` and rebuild the discovery watchlist.
- `scripts/run_realtime_monitor.sh` already accepts `EXTERNAL_SIGNALS=data/external-signals.ndjson` when building the realtime watchlist.
- `scripts/background_manager.sh` can periodically run external-signal refreshes under tmux-style orchestration.
- Existing LLM/rule-discovery work can be reused to understand market rules and resolution text.

The gap: there is no source-specific pipeline that says, for a given market, which external fact to monitor, where to monitor it, how to extract it, and how to validate whether it created tradable edge.

## Recommended Approach

Use a targeted source-connector approach, not broad crawling.

Broad crawling is expensive and noisy. It creates too much content for the LLM, too many false positives, and too many site-specific maintenance problems. It also makes it hard to prove that a signal arrived before the market moved.

Recommended first version:

1. Classify markets into external fact needs.
2. Enable only a few trusted source families with APIs/RSS/search endpoints.
3. Store raw documents and extracted facts separately.
4. Map facts to markets with deterministic filters plus LLM verification.
5. Run a forward-return report before considering any trading logic.

## Source Families for MVP

These source families are good first candidates because they are public, structured enough to collect, and often contain market-moving facts.

| Source family | Use case | Why it is worth testing | Official docs |
|---|---|---|---|
| SEC EDGAR | company filings, 8-K, 10-K, 10-Q, ownership, company facts | official corporate disclosures can resolve or move business/company markets | https://www.sec.gov/search-filings/edgar-application-programming-interfaces |
| Federal Register | US agency rules, notices, executive/regulatory actions | official government publication stream; useful for regulation/policy markets | https://www.federalregister.gov/reader-aids/developer-resources/rest-api |
| CourtListener | US legal opinions/dockets when available | court outcomes can resolve legal/case markets | https://www.courtlistener.com/help/api/rest/ |
| GDELT | discovery only, not final truth source | can help discover global news/doc mentions, but should not be treated as authoritative resolution evidence | https://www.gdeltproject.org/data.html |

Important: GDELT/news-like sources should be discovery inputs only unless the market rules explicitly allow them as resolution sources. For resolution-sensitive markets, prefer official documents.

## Non-Goals

- Do not build a crawler that scrapes every website.
- Do not scrape social media firehoses in the first PR.
- Do not turn signals into live orders.
- Do not add secrets, API keys, or paid data dependencies to tracked files.
- Do not revive the maker/cross-platform arbitrage thesis in this task.
- Do not assume every LLM match is a tradable edge; validation must prove it.

## Data Flow

```text
Polymarket Gamma / existing market cache
    -> market fact-needs classifier
    -> source-specific queries
    -> raw external documents NDJSON
    -> LLM fact extractor
    -> market/fact mapper
    -> external_signal NDJSON
    -> watchlist priority boost + realtime monitor
    -> forward-return signal report
```

The `external_signal` file remains the integration boundary with current watchlist/realtime code. New work should happen before that boundary and after it in reporting.

## Component 1: Market Fact-Needs Classifier

Purpose: convert each active market into a small set of factual monitoring needs.

Input:

- market ID / condition ID / tokens
- title/question
- description and rules text
- end date
- category/tags
- any known resolution source URL/text from existing rule extraction

Output row schema:

```json
{
  "type": "market_fact_need",
  "schema_version": 1,
  "market_id": "...",
  "condition_id": "...",
  "question": "...",
  "event_type": "regulatory_notice|sec_filing|court_decision|election|economic_release|sports_result|other",
  "entities": [
    {"name": "...", "kind": "company|agency|court|person|country|team|other", "aliases": ["..."]}
  ],
  "needed_fact": "Plain-English fact that would resolve or materially update the market.",
  "deadline_utc": "2026-...",
  "preferred_source_family": "sec_edgar|federal_register|courtlistener|gdelt_discovery|manual",
  "source_query": {"query": "...", "filters": {"...": "..."}},
  "resolution_source_hint": "...",
  "automation_eligible": true,
  "confidence": 0.0,
  "notes": "..."
}
```

Rules:

- If the resolution rules name a source, prefer that source.
- If no reliable source can be inferred, mark `automation_eligible=false`.
- Do not send all markets to every connector. The classifier must narrow the source family first.
- Keep a reason/evidence field so manual review can audit why a market was routed to a source.

## Component 2: Source Connectors

Purpose: collect raw documents from a small set of source families using official APIs where possible.

Suggested CLI shape:

```bash
python3 -m poly_strategy.cli collect-external-docs \
  --fact-needs data/market-fact-needs.ndjson \
  --source sec_edgar \
  --out data/external-raw-docs.ndjson
```

Initial connectors:

- `sec_edgar`: query company submissions/company facts and recent filings for relevant company entities.
- `federal_register`: query recent documents by agency/search term/date window.
- `courtlistener`: query opinions/dockets by court/case/entity where the market rules make this useful.
- `gdelt_discovery`: optional discovery-only connector for mentions, not final evidence.

Raw document schema:

```json
{
  "type": "raw_external_doc",
  "schema_version": 1,
  "source_family": "sec_edgar|federal_register|courtlistener|gdelt_discovery",
  "source_id": "stable-source-document-id",
  "url": "https://...",
  "published_at": "2026-...Z",
  "retrieved_at": "2026-...Z",
  "title": "...",
  "entities_hint": ["..."],
  "market_ids_hint": ["..."],
  "body_text": "short normalized text or extracted relevant sections",
  "raw": {"source_specific": "payload"}
}
```

Connector requirements:

- Deduplicate by `source_family + source_id`.
- Preserve `published_at` and `retrieved_at`; validation depends on time ordering.
- Store enough evidence text for LLM extraction, but avoid dumping huge documents when a relevant section can be selected.
- Fail soft per source; one broken connector should not stop other connectors.
- Respect public API rate limits and identify the client where required.

## Component 3: LLM Fact Extractor

Purpose: convert raw documents into strict, auditable structured facts.

Suggested CLI shape:

```bash
python3 -m poly_strategy.cli extract-structured-facts \
  --raw-docs data/external-raw-docs.ndjson \
  --fact-needs data/market-fact-needs.ndjson \
  --out data/structured-facts.ndjson
```

Structured fact schema:

```json
{
  "type": "structured_fact",
  "schema_version": 1,
  "source_family": "sec_edgar",
  "source_id": "...",
  "url": "https://...",
  "published_at": "2026-...Z",
  "extracted_at": "2026-...Z",
  "canonical_fact": "One sentence factual claim.",
  "entities": [{"name": "...", "kind": "..."}],
  "event_type": "...",
  "trigger_status": "direct_trigger|material_update|weak_signal|unrelated",
  "evidence_text": "short quote or excerpt supporting the fact",
  "candidate_market_ids": ["..."],
  "confidence": 0.0,
  "risk_flags": ["ambiguous_entity", "stale_document", "not_resolution_source"]
}
```

LLM requirements:

- Use structured JSON output only.
- Include a short evidence excerpt and URL for every non-`unrelated` fact.
- Prefer recall in extraction, then precision in mapping.
- Mark ambiguity instead of forcing a match.
- The extractor must not create a trade recommendation.

## Component 4: Market/Fact Mapper

Purpose: decide whether a structured fact applies to one or more markets and convert high-confidence matches into existing `external_signal` rows.

Mapping should use two layers:

1. Deterministic filters: entity aliases, source family, date window, market status, resolution source hints.
2. LLM verification: compare `canonical_fact + evidence_text` against the market question/rules.

External signal output should keep compatibility with `poly_strategy/external_signals.py`, but add useful fields under `raw`:

```json
{
  "type": "external_signal",
  "schema_version": 1,
  "source": "external_fact_pipeline",
  "source_id": "sec_edgar:...:market_id",
  "ts": "2026-...Z",
  "kind": "external_fact",
  "event_title": "...",
  "quoted_edge": null,
  "quoted_roi": null,
  "quoted_depth": null,
  "legs": [
    {"venue": "polymarket", "market_id": "...", "token": null, "side": "watch"}
  ],
  "raw": {
    "source_family": "sec_edgar",
    "url": "https://...",
    "published_at": "2026-...Z",
    "canonical_fact": "...",
    "trigger_status": "direct_trigger",
    "evidence_text": "...",
    "mapping_confidence": 0.0,
    "expected_direction": "yes|no|unknown",
    "risk_flags": []
  }
}
```

`expected_direction` may be useful for evaluation, but it must be optional. If direction is uncertain, emit `unknown` and let reporting separate directional from non-directional signals.

## Component 5: Forward-Return Signal Report

Purpose: prove or disprove edge before any trading work.

Suggested CLI shape:

```bash
python3 -m poly_strategy.cli external-fact-signal-report \
  --signals data/external-signals.ndjson \
  --books data/realtime-books.ndjson \
  --out reports/external-fact-signal-report-YYYY-MM-DD.md
```

Metrics:

- Number of active markets classified.
- Number of fact needs by source family.
- Number of raw documents collected by source family.
- Number of structured facts by trigger status.
- Number of mapped signals by source family and market type.
- Manual audit precision on a sample of mapped signals.
- Time from `published_at` to `retrieved_at` to `external_signal.ts`.
- Forward mid-price movement at 5m, 30m, 2h, 24h.
- Directional hit rate where `expected_direction` is known.
- Simulated tradability after spread/depth, not just mid-price movement.

Validation rules:

- Count a signal only if the raw document's `published_at` is before the measured market move.
- Separate "fact arrived after price moved" from "fact arrived before price moved".
- Do not claim edge from stale documents.
- Report spread-adjusted and depth-limited results separately from raw mid-price movement.

## Acceptance Criteria for First PR Series

A good first implementation should satisfy all of these before we call the direction promising:

- Produces `market_fact_need` rows for a representative active-market sample.
- Routes markets to at least three source families: SEC EDGAR, Federal Register, and CourtListener.
- Writes deduped `raw_external_doc` rows with source URL, `published_at`, and `retrieved_at`.
- Writes `structured_fact` rows with evidence text and confidence.
- Emits compatible `external_signal` rows for mapped Polymarket markets.
- Existing watchlist/realtime flow can consume the emitted `external_signal` file without code rewrites.
- Produces a Markdown/JSON report that separates coverage, precision, timeliness, price movement, and tradability.
- Includes tests for schema validation, deduplication, source routing, and mapper behavior.

## Kill Criteria

Stop or redesign the direction if the shadow run shows any of these:

- Fewer than 10 high-confidence mapped signals per week after source routing is working.
- Manual audit precision below 70% for mapped `direct_trigger` or `material_update` rows.
- Most signals are retrieved after the relevant market has already moved.
- Forward movement exists only in mid-price but disappears after spread/depth assumptions.
- Source maintenance cost is high because too many custom scrapers are required.

## Suggested PR Split

PR 1: market fact-needs classifier and report

- Add `market_fact_need` schema and CLI.
- Use existing market/rule caches.
- No external collection yet.
- Output a report showing which markets are automatable and which source family they need.

PR 2: official source connectors

- Add SEC EDGAR, Federal Register, and CourtListener collectors.
- Write `raw_external_doc` NDJSON.
- Include dedupe, timestamps, and rate-limit handling.
- Keep GDELT optional/discovery-only if added.

PR 3: LLM fact extractor and mapper

- Add structured fact extraction.
- Add deterministic + LLM market mapping.
- Emit compatible `external_signal` rows.

PR 4: outcome evaluation

- Join emitted signals to realtime/order-book snapshots.
- Produce forward-return and tradability reports.
- Include a manual audit sample export.

This split is preferred because each PR can be reviewed independently and can fail without blocking the others.

## Open Questions for Soli22de

- Is PR 1 enough as the first contribution, or should PR 1 include one source connector for end-to-end proof?
- Which market categories in current Gamma data look most suitable for SEC/Federal Register/CourtListener routing?
- Should the extractor use the current LLM profile stack, or should it define a separate cheaper/high-recall profile?
- How large should the manual audit sample be for the first shadow run?
- Should `expected_direction` be required only for `direct_trigger`, or optional for all signal rows?

## Implementation Notes

- Keep all new runtime outputs under `data/` or `reports/`; do not commit generated data.
- Prefer append-only NDJSON for raw docs, facts, and signals so tmux/background loops can run safely.
- Add compaction for new large NDJSON files only after the first connector proves useful.
- Use existing CLI style in `poly_strategy/cli.py` and existing test style under `tests/`.
- Keep source adapters isolated from LLM extraction so we can test them without provider keys.
- Add deterministic fixtures for unit tests; do not depend on live network in tests.

## Definition of Done

The direction is ready for deeper implementation when we have:

1. A working shadow pipeline from market fact need to external signal.
2. At least one week of reports showing coverage, precision, timeliness, and tradability.
3. Clear evidence that the pipeline finds facts the current monitor would not otherwise prioritize.
4. A decision on whether to expand sources, improve mapping, or stop the direction.
