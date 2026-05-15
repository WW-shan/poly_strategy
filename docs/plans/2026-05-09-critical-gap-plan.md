# 2026-05-09 Critical Gap Plan

This file is the persistent execution checklist for the Polymarket arbitrage MVP. Keep it updated after every implementation block so the work does not disappear from context.

## Objective

Build a safe, fully automated dry-run research/trading loop that can discover more markets, scan realtime order books, explain why opportunities are absent, emit alerts, build pretrade-checked execution plans, and run persistently on macOS. Live trading remains disabled until separate explicit approval and key-safety work.

## Current Baseline

- Polymarket internal strategies exist: YES/NO bundle, implication, mutual exclusion, equivalence, complement, exhaustive groups, neg-risk baskets, and near-miss diagnostics.
- Realtime Polymarket WebSocket monitor exists and currently watches `data/watchlist-current.json`.
- Alert extraction exists and writes NDJSON with cooldown state.
- Execution planning exists as dry-run only by default.
- External signal normalization exists for manually supplied scanner payloads.
- Persistent local orchestration runs through `scripts/background_manager.sh`, which starts the manager in tmux when tmux is available.

## Critical Gap Checklist

- [ ] Close the current six production gaps before treating the system as usable.
  - [x] Oddpool must be plan-aware: Free plan uses Search endpoints, Premium arbitrage endpoints are disabled unless explicitly requested.
  - [x] Oddpool Free payloads must normalize recent/search market and event rows, not only arbitrage rows.
  - [x] Oddpool Free must keep a local quota ledger for 1 req/sec and 1000 requests/month.
  - [x] Cross-platform matches must be semantic-verified before they can become actionable dry-run signals.
  - [x] Kalshi/Polymarket cross-platform output must stop hardcoding executable YES/NO legs for unverified matches.
  - [x] Execution must write live-attempt/reconciliation state into the risk ledger after real submissions.
  - [x] Data rotation must run inside the persistent background manager, not only as a manual script.
  - [x] Rule discovery must broaden beyond deterministic neg-risk pairs with topic clustering and safer non-neg-risk candidates.
- [x] Expand opportunity coverage beyond the current small watchlist.
  - [x] Rank high-liquidity/high-relevance Polymarket markets.
  - [x] Include high-liquidity single-market YES/NO bundles.
  - [x] Include all viable neg-risk groups/baskets from Gamma metadata.
  - [x] Include discovered relation-rule markets.
  - [x] Produce a larger prioritized watchlist without blindly subscribing to every market.
- [x] Add automatic incremental market discovery.
  - [x] Pull fresh Gamma markets on a schedule.
  - [x] Run LLM/rule discovery only on new markets.
  - [x] Reuse rule cache for previously processed markets.
  - [x] Rebuild watchlist after discovery.
  - [x] Restart/reload realtime monitor when the watchlist changes.
- [x] Add realtime-specific analysis reports.
  - [x] Opportunity frequency and zero-opportunity streaks.
  - [x] Near-miss distribution.
  - [x] Fee drag diagnostics.
  - [x] Spread/price-distance reasons for no opportunities.
  - [x] Closest market/rule candidates.
  - [x] WebSocket health, stale/reconnect, and message-age metrics.
- [x] Complete alert to execution dry-run linkage.
  - [x] Read latest alert/monitor state.
  - [x] Refresh quote/orderbook before plan creation.
  - [x] Build dry-run execution plan.
  - [x] Run pretrade checks.
  - [x] Keep live execution blocked unless explicitly enabled.
- [x] Add notification outputs.
  - [x] Webhook JSON notification.
  - [x] Telegram-compatible notification.
  - [x] Discord-compatible notification.
  - [x] Local desktop notification command path.
- [x] Add production data maintenance.
  - [x] Date/file rotation helper.
  - [x] Compress old raw/snapshot files.
  - [x] Retain reports and alert logs.
  - [x] Guard against disk exhaustion.
- [x] Background production data maintenance.
  - [x] Run `scripts/rotate_data.sh` from the persistent background manager.
  - [x] Start/restart it through the tmux-backed manager script.
  - [x] Smoke-test rotation in dry-run mode and rotate current oversized snapshot data.
- [x] Convert background jobs to persistent local manager tasks.
  - [x] Realtime monitor task.
  - [x] Alert loop task.
  - [x] Optional discovery refresh task.
  - [x] Start/restart/status helper script.
- [x] Build cross-platform/Kalshi framework.
  - [x] Kalshi market collector.
  - [x] Kalshi orderbook parser/collector.
  - [x] Polymarket/Kalshi matching candidates.
  - [x] Cross-platform fee/funding/risk model.
  - [x] Dry-run-only cross-platform execution risk report.
- [x] Upgrade cross-platform/Kalshi from candidate framework to verified dry-run signals.
  - [x] Add deterministic semantic verification fields to match reports.
  - [x] Emit only watch/verified binary legs, not hardcoded Polymarket YES / Kalshi NO execution legs.
  - [x] Keep unverified matches as priority/research signals only.
  - [x] Add a one-shot verified Polymarket/Kalshi HTTP orderbook dry-run scanner.
- [x] Integrate external tool signals into the realtime loop.
  - [x] Poll generic external signal URLs/files.
  - [x] Normalize Oddpool/PillarLabAI/Polyprophet-style payloads through the existing signal schema.
  - [x] Convert high-confidence signals into watchlist priority boosts.
- [x] Make Oddpool integration Free-plan safe.
  - [x] Default `ODDPOOL_PLAN=free`.
  - [x] Use `/search/recent/markets` and optional `/search/markets` queries for Free.
  - [x] Refuse or ignore `/arbitrage/current` while Free mode is active.
  - [x] Add local quota/rate ledger.
  - [x] Add tests for Free payload normalization and script endpoint selection.
- [x] Add live-risk controls while keeping live trading disabled.
  - [x] Daily max loss.
  - [x] Per-trade max loss/notional.
  - [x] Max order count.
  - [x] Kill switch.
  - [x] Partial-fill/reconciliation placeholders.
  - [x] Balance/API-key safety checks.
  - [x] Failure cooldown/pause mechanism.
- [x] Upgrade live-risk controls from placeholders to stateful reconciliation.
  - [x] Classify dry-run/live responses.
  - [x] Detect unknown/partial/failure states requiring reconciliation.
  - [x] Update daily risk state after live submission attempts.
- [x] Broaden rule coverage beyond neg-risk.
  - [x] Add topic-clustered LLM batching.
  - [x] Add conservative deterministic equivalent detection for exact duplicate binary questions.
  - [x] Keep ambiguous deterministic candidates blocked unless verified.
- [x] Final validation.
  - [x] Unit tests.
  - [x] Smoke tests with current data.
  - [x] Code review checklist.
  - [x] Git commit for each key block.

## Execution Notes

- Use `.venv/bin/python` for commands and tests.
- Default proxy for live HTTP smoke tests can be `127.0.0.1:10808` when needed.
- Do not place API keys, private keys, or secrets in this repository.
- Do not enable live order posting in automation; only dry-run plans are allowed for this phase.

## 2026-05-10 Validation Update

- [x] Re-ran the full unit test suite after installing pytest in `.venv`.
- [x] Fixed cross-platform LLM verification parsing when OpenAI-compatible gateways return `results` rows without `confidence`.
- [x] Verified the fallback Responses endpoint parses 20/20 cross-platform candidates and safely rejected all 20 sample false positives.
- [x] Ran a 1000-market realtime probe with HTTP orderbook seeding.
  - Result: 853 market snapshots per iteration, 30 iterations, 0 actionable positive-net opportunities.
  - Best actionable candidate remained below threshold: YES/NO bundle net edge about -0.00109/share.
- [x] Investigated large positive diagnostic baskets.
  - Weather range groups were false positives because the upper or lower tail outcome was missing.
  - Nobel named-candidate groups were false positives because no `Other`/field outcome existed.
- [x] Added deterministic exhaustive-basket rejection for ordered numeric ranges and open-ended award candidate groups.
- [x] Added passive maker dry-run scanning for baskets.
  - Default mode quotes one tick below the best ask to avoid misleading zero-bid fantasy fills.
  - Current 1000-market probe found 11 near-ask maker candidates, but the best expected edge at a $100 cap was only about $0.21 before partial-fill/adverse-selection risk.
  - These are not safe live trades yet; they require all legs to fill and remain dry-run only.
- [x] Added an overwrite-only latest snapshot file for realtime scans, so wider watchlists can feed maker diagnostics without relying only on ever-growing raw snapshot logs.
- [x] Raised default realtime watchlist coverage to 1000 markets with more high-liquidity and neg-risk groups.
- [x] Added conservative maker fill simulation.
  - A maker buy leg counts as possibly filled only if a later snapshot shows `best_ask <= our_limit`.
  - Current short-window result: no completed fills observed yet.
  - This means the maker candidates are currently theoretical only; they need longer paper observation or different quote logic before live use.
- [x] Added adaptive maker quote simulation.
  - Compares near-ask offsets of 1/2/3/5/10 ticks plus bid-improvement quotes.
  - Ranks each quote config by conservative risk-adjusted EV: completed edge minus a configurable haircut for partial-fill capital.
  - Current short-window result with a $100 cap: no positive-EV quote config; near-ask offsets showed partial fills without complete basket fills, which is a strong live-trading rejection signal.
- [x] Made LLM discovery plan-aware and bounded.
  - Provider order is chat `glm-5.1` primary, chat `glm-5.1` backup, then Responses `gpt-5.4` fallback.
  - Chat providers use shorter timeouts so a broken/blocked chat route does not stall the full monitor loop.
  - Each refresh can cap uncached markets sent to LLM; the remaining markets stay pending for later incremental discovery.
  - Latest smoke test: both chat routes timed out, then Responses fallback completed and added a new implication rule.
- [x] Added success-status monitoring.
  - Writes the current state of paper, dry-run execution, live execution, and maker EV into `data/success-status-current.json`.
  - Background manager runs it continuously and appends only non-empty success states to `data/success-events.ndjson`.
- [x] Made long LLM discovery non-blocking for the supervisor loop.
  - Realtime monitor keeps running independently.
  - Alerts, dry-run execution checks, maker scans, and success-status checks no longer wait for hourly LLM discovery to finish.

## Current Profitability Status

- The automation chain can collect, seed, monitor, analyze, alert, and dry-run execution plans.
- It has not found a currently executable opportunity with positive net edge and usable ROI for a $100 bankroll.
- The most important current result is negative but useful: the system is now rejecting high-edge-looking traps instead of promoting them as trades.

## Next Useful Work

- [ ] Keep the realtime monitor running in paper mode and collect at least 24 hours of stable-paper-trade evidence before enabling any live order path.
- [x] Add a maker-order research module that computes passive bid limits for complete/neg-risk baskets; this is not pure arbitrage and stays dry-run until fill/reconciliation risk is modeled.
- [x] Add maker fill simulation from WebSocket/snapshot deltas so candidates are ranked by realized fill probability, not only theoretical edge.
- [x] Add adaptive quote placement that compares near-ask edge against observed fill probability and rejects expected-value-negative quotes.
- [ ] Improve cross-platform matching beyond token Jaccard by adding event/category filters and rejecting Kalshi multi-leg combo markets before LLM verification.
- [ ] Add ROI-first opportunity ranking so small-bankroll alerts prioritize executable dollars and not only edge per share.
- [x] Add a compact latest-snapshot store so wide probes can be run without writing tens of MB per minute.
- [ ] Keep investigating the chat `glm-5.1` endpoints; they currently time out on strict JSON-schema discovery, so they are tried first but not trusted as the only discovery route.
