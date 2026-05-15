# Command Reference

This is the detailed command reference for `poly_strategy`.

This is not an auto-trader. The first goal is to record snapshots and test whether fee-aware opportunities survive realistic filters.

## Commands

Create a synthetic snapshot:

```bash
python3 -m poly_strategy.cli sample --out data/sample.ndjson
```

Replay snapshots:

```bash
python3 -m poly_strategy.cli backtest data/sample.ndjson
```

Try collecting Polymarket Gamma market metadata:

```bash
python3 -m poly_strategy.cli collect-polymarket --out data/polymarket-gamma.ndjson --limit 20 --timeout 10
```

Use a local HTTP proxy if direct access is unstable:

```bash
python3 -m poly_strategy.cli collect-polymarket --out data/polymarket-gamma.ndjson --limit 20 --timeout 10 --proxy 127.0.0.1:10808
```

Collect multiple Gamma pages when building a broader metadata cache:

```bash
python3 -m poly_strategy.cli collect-polymarket \
  --out data/polymarket-gamma.ndjson \
  --limit 100 \
  --pages 2 \
  --proxy 127.0.0.1:10808
```

Try collecting specific Polymarket CLOB books:

```bash
python3 -m poly_strategy.cli collect-polymarket --out data/books.ndjson --token-id TOKEN_ID --timeout 10
```

Discover conservative implication rules from raw Gamma market metadata with an OpenAI-compatible Responses API:

```bash
export OPENAI_API_KEY=...
export OPENAI_MODEL=...
export OPENAI_BASE_URL=https://api.openai.com/v1

python3 -m poly_strategy.cli discover-rules \
  --raw data/polymarket-gamma.ndjson \
  --out rules/candidate-implications.json \
  --batch-size 10 \
  --min-confidence 0.95 \
  --max-markets 100 \
  --max-output-tokens 4000 \
  --reasoning-effort medium
```

You can also pass the model and base URL explicitly:

```bash
python3 -m poly_strategy.cli discover-rules \
  --raw data/polymarket-gamma.ndjson \
  --out rules/candidate-implications.json \
  --model MODEL_NAME \
  --base-url https://api.openai.com/v1
```

The LLM stage only proposes semantic relations. It does not place trades and does not receive orderbook prices.

Supported deterministic relation formats:

- `implications`: if `A YES => B YES`, scan `buy B YES + buy A NO < 1 - costs`.
- `equivalent`: if `A YES iff B YES`, scan both `buy A YES + buy B NO` and `buy B YES + buy A NO`.
- `mutually_exclusive`: if `A YES` and `B YES` cannot both happen, scan `buy A NO + buy B NO`.
- `collectively_exhaustive`: if at least one of `A YES` or `B YES` must happen, scan `buy A YES + buy B YES`.
- `exhaustive_groups`: if a reviewed set is complete and exactly one member must resolve YES, scan `buy all YES` when `sum(YES) < 1 - costs`.
- `complement`: if exactly one of `A YES` or `B YES` must happen, scan both `YES + YES` and `NO + NO` bundles.

Example exhaustive group rule:

```json
{
  "exhaustive_groups": [
    {
      "market_ids": ["team-a-wins", "team-b-wins", "team-c-wins"],
      "confidence": 0.99,
      "trade_allowed": true,
      "risk_flags": []
    }
  ]
}
```

Only add an `exhaustive_groups` entry after verifying the markets are the full outcome set for the same resolution event. Near-miss rows named `potential_exhaustive_yes_basket` are diagnostic only until promoted to this reviewed format.

To ask the LLM to verify the strongest diagnostic groups and promote only high-confidence complete sets:

```bash
python3 -m poly_strategy.cli verify-exhaustive-groups \
  --gamma data/polymarket-gamma.ndjson \
  --rules-in rules/candidate-implications.json \
  --rules-out rules/candidate-implications-with-groups.json \
  --snapshots data/paper-monitor-snapshots.ndjson \
  --model gpt-5.5 \
  --base-url https://api.openai.com/v1 \
  --min-net-edge 0.002 \
  --top 5 \
  --report-out data/exhaustive-group-verification.json
```

This command only writes rule JSON. It does not trade. A group is promoted only when the verifier returns `verdict=exhaustive_group`, `trade_allowed=true`, no risk flags, and confidence above `--min-confidence`.

For incremental discovery, reuse a previous rule file as cache:

```bash
python3 -m poly_strategy.cli discover-rules \
  --raw data/polymarket-gamma.ndjson \
  --out rules/candidate-implications.json \
  --cache rules/candidate-implications.json \
  --model gpt-5.5 \
  --base-url https://api.openai.com/v1
```

New rule files include `processed_market_ids`, so a later incremental run skips markets that were already reviewed even if the LLM found no relation for them. If the cache fully covers the raw input, `discover-rules --cache ...` can refresh the normalized rule file without an API call or model.

Collect only markets referenced by a rule file:

```bash
python3 -m poly_strategy.cli collect-rule-markets \
  --gamma data/polymarket-gamma.ndjson \
  --rules rules/candidate-implications.json \
  --out data/rule-markets.ndjson \
  --proxy 127.0.0.1:10808 \
  --book-workers 8
```

By default, targeted collection expands any referenced Polymarket `negRiskMarketID` to every known market in that same group. This is required for complete group baskets such as `sum(all YES) < 1`. Pass `--no-expand-neg-risk-groups` only when debugging a narrow rule file.

Build the standardized token watchlist that a future WebSocket subscriber should use:

```bash
python3 -m poly_strategy.cli build-watchlist \
  --gamma data/polymarket-gamma.ndjson \
  --rules rules/candidate-implications.json \
  --out data/watchlist.json
```

Stream the watchlist through Polymarket's market WebSocket and append normalized orderbook updates plus backtestable binary snapshots:

```bash
python3 -m poly_strategy.cli stream-polymarket-watchlist \
  --watchlist data/watchlist.json \
  --out data/realtime-orderbooks.ndjson \
  --snapshots-out data/realtime-snapshots.ndjson \
  --snapshot-interval 2
```

This command requires the optional live dependency:

```bash
/opt/homebrew/bin/python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-live.txt
```

The snapshot rows keep the watchlist `fee_rate`, so they can be replayed by the same `backtest`, `paper-report`, and `execute-latest` commands used for HTTP-collected snapshots.

For the lower-latency paper-trading path, scan live WebSocket snapshots in-process and append one JSONL report row per scan interval:

```bash
python3 -m poly_strategy.cli realtime-monitor-watchlist \
  --watchlist data/watchlist.json \
  --rules rules/candidate-implications.json \
  --gamma data/polymarket-gamma.ndjson \
  --report-out data/realtime-monitor.jsonl \
  --snapshots-out data/realtime-monitor-snapshots.ndjson \
  --updates-out data/realtime-monitor-updates.ndjson \
  --snapshot-interval 2 \
  --min-net-edge 0.002 \
  --max-capital-per-trade 20 \
  --bankroll 100 \
  --min-paper-roi 0.01 \
  --min-run-observations 2 \
  --min-run-seconds 3
```

Use `--max-messages` or `--max-iterations` for bounded smoke tests. The realtime monitor uses the same rule set, neg-risk baskets, stable-run filters, conflict-aware paper selection, and quality filters as the HTTP `paper-monitor`, but avoids polling each CLOB book over HTTP.

For a standardized long-running monitor through the project virtualenv:

```bash
REPORT_OUT=data/realtime-monitor-24h-v1.jsonl \
SNAPSHOTS_OUT=data/realtime-monitor-24h-v1-snapshots.ndjson \
SNAPSHOT_INTERVAL=2 \
STALE_TIMEOUT=30 \
RECONNECT_DELAY=2 \
scripts/run_realtime_monitor.sh
```

The script rebuilds `data/watchlist-current.json`, uses `.venv/bin/python`, reconnects on stale WebSocket feeds, and does not write raw update rows unless `UPDATES_OUT=...` is set.

For the managed local loop, use the background manager:

```bash
scripts/background_manager.sh start
scripts/background_manager.sh status
scripts/background_manager.sh stop
```

Extract standardized alert rows from the latest monitor iteration:

```bash
python3 -m poly_strategy.cli monitor-alerts data/realtime-monitor.jsonl \
  --min-paper-roi 0.01 \
  --out data/opportunity-alerts.ndjson \
  --state data/opportunity-alerts-state.json \
  --cooldown-seconds 60
```

`monitor-alerts` reads either `paper-monitor` or `realtime-monitor-watchlist` reports and emits `opportunity_alert` JSONL rows from the latest stable paper trades. Add `--include-current` if you also want non-paper-selected current opportunities for diagnostics or notifications.

For the current realtime run, the background manager runs the alert pass every 60 seconds by default:

```bash
scripts/background_manager.sh start
scripts/background_manager.sh status
scripts/background_manager.sh tail
```

Watch those markets repeatedly and replay opportunities:

```bash
python3 -m poly_strategy.cli monitor-rules \
  --gamma data/polymarket-gamma.ndjson \
  --rules rules/candidate-implications.json \
  --out data/rule-monitor.ndjson \
  --interval 5 \
  --iterations 12 \
  --min-net-edge 0.002 \
  --max-capital-per-trade 20 \
  --book-workers 8
```

`monitor-rules` appends each targeted snapshot batch, replays the cumulative file, and prints current-iteration opportunities plus active run duration/edge when any opportunity survives the `--min-net-edge` filter.

For a longer paper-trading run, use `paper-monitor`. It keeps the same targeted collection loop, scans only the newly appended snapshot batch on each iteration, and writes structured JSONL for every iteration plus a final summary. Use `--skip-book-errors` so one failed CLOB book does not discard the whole batch, and `--continue-on-error` for unattended runs:

```bash
python3 -m poly_strategy.cli paper-monitor \
  --gamma data/polymarket-gamma.ndjson \
  --rules rules/candidate-implications.json \
  --snapshots-out data/paper-monitor-snapshots.ndjson \
  --report-out data/paper-monitor-report.jsonl \
  --proxy 127.0.0.1:10808 \
  --interval 5 \
  --iterations 17280 \
  --book-workers 8 \
  --min-net-edge 0.002 \
  --max-capital-per-trade 20 \
  --bankroll 100 \
  --min-paper-roi 0.01 \
  --min-run-observations 2 \
  --min-run-seconds 3 \
  --skip-book-errors \
  --continue-on-error
```

At a 5 second interval, `--iterations 17280` is roughly one day. The report rows include current opportunities, stable opportunities after the run-duration filter, simulated stable paper trades, collection error counts, active run details, and cumulative paper totals for the current process. Existing rows in `--snapshots-out` are left untouched but are not replayed into the new monitor state, so use a fresh report path for each serious run.

Summarize a paper monitor run:

```bash
python3 -m poly_strategy.cli paper-analyze data/paper-monitor-report.jsonl \
  --out data/paper-monitor-analysis.json \
  --top 10
```

Add `--snapshots` and `--rules` to include near-miss diagnostics for the latest snapshot batch:

```bash
python3 -m poly_strategy.cli paper-analyze data/paper-monitor-report.jsonl \
  --snapshots data/paper-monitor-snapshots.ndjson \
  --rules rules/candidate-implications.json \
  --gamma data/polymarket-gamma.ndjson \
  --near-miss-min-net-edge 0.002 \
  --out data/paper-monitor-analysis.json \
  --top 20 \
  --near-miss-top 20
```

The analysis report includes error rate, runtime, opportunity observations, stable opportunity observations, stable paper ROI, edge distributions, top recurring opportunities, and top stable markets. With near-miss diagnostics, it also reports the closest fee-adjusted candidates, the raw gross edge before fees, fee drag, top-of-book size, and candidates where a raw price edge disappears after Polymarket taker fees.

When `--gamma` is provided, near-miss diagnostics also explain why a `potential_exhaustive_yes_basket` is not tradeable. For known neg-risk groups, the report lists omitted markets, missing snapshots for the full group, and a diagnostic `known_neg_risk_full_yes_basket` calculation when every known group member has a current orderbook snapshot.

Write a conflict-aware paper trading report. This sorts opportunities by edge per capital, reserves overlapping leg liquidity so the same visible ask depth is not counted twice, and applies both per-trade and per-iteration bankroll caps:

```bash
python3 -m poly_strategy.cli paper-report data/rule-monitor.ndjson \
  --rules rules/candidate-implications.json \
  --min-net-edge 0.002 \
  --max-capital-per-trade 20 \
  --bankroll 100 \
  --out data/paper-report.json
```

Build dry-run execution plans from the latest snapshot batch:

```bash
python3 -m poly_strategy.cli execute-latest data/rule-monitor.ndjson \
  --rules rules/candidate-implications.json \
  --min-net-edge 0.002 \
  --min-paper-roi 0.01 \
  --min-run-observations 2 \
  --min-run-seconds 3 \
  --max-capital-per-trade 20 \
  --bankroll 100 \
  --require-single-level \
  --require-pretrade-pass \
  --out data/execution-plans.ndjson
```

Execution plans include a `pretrade_check` block with token presence, BUY-only validation, leg count, worst-price checks, single-level fill checks, paper ROI, and active run details. Use `--max-leg-count`, `--max-worst-price`, `--require-single-level`, and `--require-pretrade-pass` to turn these checks into hard gates.

Normalize alerts from an external scanner such as Oddpool into the local signal format. These alerts are candidates only; the local scanner still has to verify orderbook depth and rule semantics before any paper or execution plan is created:

```bash
python3 -m poly_strategy.cli ingest-external-signals \
  --source oddpool \
  --input data/oddpool-signals.json \
  --out data/external-signals.ndjson

python3 -m poly_strategy.cli external-signal-report data/external-signals.ndjson \
  --out data/external-signal-report.json
```

For a safer pre-trade path, refresh the targeted rule-market books immediately before planning:

```bash
python3 -m poly_strategy.cli execute-rules-once \
  --gamma data/polymarket-gamma.ndjson \
  --rules rules/candidate-implications.json \
  --snapshots-out data/execute-refresh.ndjson \
  --out data/execution-plans.ndjson \
  --proxy 127.0.0.1:10808 \
  --book-workers 8 \
  --min-net-edge 0.002 \
  --min-run-observations 1 \
  --max-capital-per-trade 20 \
  --bankroll 100
```

Live submission is intentionally disabled by default. To submit with the official Polymarket CLOB Python SDK v2, install `py_clob_client_v2`, set `POLYMARKET_PRIVATE_KEY` and optional L2 API credential environment variables, then pass both `--live` and `--allow-live`. Multi-leg arbitrage execution is not atomic, so live submission of plans with more than one order also requires `--allow-nonatomic-live`. The generated orders are FOK buy orders with a configurable slippage cushion and tick size.

Collect backtestable binary snapshots by combining Gamma market discovery with YES/NO CLOB books:

```bash
python3 -m poly_strategy.cli collect-polymarket-binaries --out data/live-binaries.ndjson --limit 50 --timeout 12 --proxy 127.0.0.1:10808
```

Refresh Gamma metadata for specific market IDs when a near-miss candidate is missing text metadata:

```bash
python3 -m poly_strategy.cli collect-polymarket \
  --out data/polymarket-gamma.ndjson \
  --market-id 544094 \
  --market-id 544095 \
  --proxy 127.0.0.1:10808
```

Then replay them:

```bash
python3 -m poly_strategy.cli backtest data/live-binaries.ndjson
```

Run repeated collection for a short smoke test:

```bash
python3 -m poly_strategy.cli collect-polymarket-binaries \
  --out data/live-binaries.ndjson \
  --limit 25 \
  --iterations 3 \
  --interval 5 \
  --timeout 12 \
  --proxy 127.0.0.1:10808
```

Run a longer one-hour sample:

```bash
python3 -m poly_strategy.cli collect-polymarket-binaries \
  --out data/hourly-binaries.ndjson \
  --limit 50 \
  --iterations 720 \
  --interval 5 \
  --timeout 12 \
  --proxy 127.0.0.1:10808
```

Replay with small-bankroll limits:

```bash
python3 -m poly_strategy.cli backtest data/hourly-binaries.ndjson \
  --min-net-edge 0.005 \
  --max-capital-per-trade 25
```

Add hand-reviewed implication rules for markets where one event logically implies another:

```json
{
  "implications": [
    {
      "antecedent": "france-wins-world-cup",
      "consequent": "france-reaches-final"
    }
  ]
}
```

For an implication `A => B`, the scanner tests:

```text
buy B YES + buy A NO < 1 - costs
```

Replay with rules:

```bash
python3 -m poly_strategy.cli backtest data/hourly-binaries.ndjson \
  --rules rules/candidate-implications.json \
  --min-net-edge 0.005 \
  --max-capital-per-trade 25
```

Output fields:

- `opportunities`: raw detected structure opportunities.
- `total_edge`: theoretical total edge if each full visible opportunity is filled.
- `paper_trades`: opportunities after paper-trade sizing.
- `paper_rejections`: paper opportunities skipped because bankroll or overlapping visible liquidity was already reserved.
- `by_kind`: aggregate opportunity and paper-trading totals by opportunity type.
- `paper_capital`: simulated capital used after `--max-capital-per-trade`.
- `paper_edge`: edge after paper-trade sizing.
- `runs`: consecutive snapshot runs where the same opportunity persisted.

For this research stage, a signal is worth deeper work only if it repeatedly shows:

- positive `paper_edge` after a non-trivial `--min-net-edge`;
- enough `runs` with duration above your observed execution latency;
- enough capital capacity at your intended trade size.

## Snapshot Format

The current backtest consumes `binary_snapshot` rows:

```json
{"type":"binary_snapshot","venue":"polymarket","market_id":"sample","fee_rate":0.0,"yes":{"asks":[[0.45,10]],"bids":[]},"no":{"asks":[[0.53,7]],"bids":[]}}
```

It detects the simplest structure opportunity:

```text
buy YES + buy NO < 1 - costs
```

## Current Production Dry-Run Loop

The current MVP is designed to stay dry-run by default. It widens the realtime watchlist, refreshes market metadata incrementally, explains zero-opportunity periods, emits alerts, and builds risk-checked execution plans without submitting live orders.

Refresh Gamma metadata, reuse the rule cache, rebuild a larger prioritized watchlist, and restart the realtime monitor only if the watchlist changes:

```bash
SKIP_LLM=1 \
LIMIT=100 \
PAGES=5 \
INCLUDE_TOP_MARKETS=150 \
INCLUDE_TOP_NEG_RISK_GROUPS=25 \
MAX_WATCHLIST_MARKETS=250 \
scripts/refresh_discovery_watchlist.sh
```

Run a realtime-specific analysis report explaining why opportunities are absent or close:

```bash
.venv/bin/python -m poly_strategy.cli monitor-analyze data/realtime-monitor-24h-v1.jsonl \
  --snapshots data/realtime-monitor-24h-v1-snapshots.ndjson \
  --rules data/gpt55-candidate-rules-all.json \
  --gamma data/polymarket-gamma.ndjson \
  --near-miss-min-net-edge 0.002 \
  --near-miss-top 20 \
  --out data/realtime-monitor-24h-v1-analysis.json
```

The `zero_opportunity_diagnosis` section separates actionable near-misses from diagnostic or blocked candidates, so a positive-looking basket that still needs rule promotion will not be treated as executable.
The same report is refreshed by `scripts/run_realtime_analysis_once.sh`; the background manager runs it every 15 minutes by default.

Extract markets from a specific optimization lever and run a focused maker-fee scan:

```bash
.venv/bin/python -m poly_strategy.cli optimization-target-markets data/realtime-monitor-24h-v1-analysis.json \
  --lever maker_fee_avoidance \
  --top-targets 1 \
  --max-markets 120 \
  --out data/optimization-target-market-ids.txt

MAX_TARGET_MARKETS=120 TOP=50 scripts/run_maker_focus_from_analysis_once.sh
```

Validate the focused maker candidates against public SELL trade prints:

```bash
HYBRID_SCAN=data/maker-hybrid-scan-focus.json \
TRADES=data/polymarket-data-trades-focus.ndjson \
OUT=data/maker-hybrid-tape-sim-focus.json \
LOCK_DIR=var/locks/maker-hybrid-tape-focus.lock \
scripts/run_maker_hybrid_tape_once.sh
```

`maker-hybrid-tape-sim` remains diagnostic-only, but its report explains why fills did not complete with `rejection_by_reason`, `maker_fill_progress_distribution`, and `top_unfilled_maker_legs`.

Promote only usable opportunities from diagnostic basket candidates:

```bash
scripts/run_rule_promotion_once.sh
```

This script first checks whether any diagnostic exhaustive-group candidate clears `MIN_NET_EDGE`. If none do, it exits without calling the LLM. When candidates exist, it runs the verifier, caches rejected groups in `data/exhaustive-group-promotion-state.json`, writes verified groups back into the active rule file, rebuilds the watchlist, and lets the realtime monitor restart only if the watchlist changes.

Turn alerts into refreshed dry-run execution plans with pretrade and risk checks:

```bash
scripts/run_monitor_alerts_once.sh
scripts/run_execution_dry_run_once.sh
```

Send alerts to notification sinks. The script reads `ALERT_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`, and `DISCORD_WEBHOOK_URL` when present:

```bash
DRY_RUN=1 ALERT_WEBHOOK_URL=https://example.test/hook scripts/run_notify_alerts_once.sh
```

Oddpool Free is quota-limited. The background manager refreshes external signals hourly by default to stay within the 1000 requests/month budget.

Rotate large snapshot/update/log files while preserving report JSONL by default:

```bash
DRY_RUN=1 MAX_BYTES=104857600 scripts/rotate_data.sh
MAX_BYTES=104857600 RETENTION_DAYS=14 scripts/rotate_data.sh
```

## Kalshi / Cross-Platform Framework

Collect Kalshi market metadata and orderbooks, convert them to the local binary snapshot format, and generate Polymarket/Kalshi text-match candidates:

```bash
.venv/bin/python -m poly_strategy.cli collect-kalshi \
  --out data/kalshi-markets.ndjson \
  --limit 100 \
  --proxy 127.0.0.1:10808

.venv/bin/python -m poly_strategy.cli collect-kalshi-orderbooks \
  --out data/kalshi-orderbooks.ndjson \
  --ticker KXEXAMPLE \
  --proxy 127.0.0.1:10808

.venv/bin/python -m poly_strategy.cli kalshi-snapshots \
  --orderbooks data/kalshi-orderbooks.ndjson \
  --out data/kalshi-snapshots.ndjson

.venv/bin/python -m poly_strategy.cli match-cross-platform \
  --polymarket-gamma data/polymarket-gamma.ndjson \
  --kalshi-markets data/kalshi-markets.ndjson \
  --out data/cross-platform-matches.json \
  --signals-out data/external-signals.ndjson
```

Cross-platform matches are candidates only. They must still pass semantic verification, fee/funding checks, and dry-run execution risk checks before any live system is considered.

## Risk Controls

Execution planning adds `pretrade_check` and `risk_check` rows. Live posting remains blocked unless `--live --allow-live` are both passed and `POLY_STRATEGY_ALLOW_LIVE=1` plus required private keys are present.

Useful risk flags:

```bash
.venv/bin/python -m poly_strategy.cli execute-latest data/realtime-alert-execution-refresh.ndjson \
  --rules data/gpt55-candidate-rules-all.json \
  --gamma data/polymarket-gamma.ndjson \
  --out data/checked-plans.ndjson \
  --max-trade-notional 10 \
  --max-daily-loss 25 \
  --max-daily-orders 20 \
  --kill-switch data/KILL_SWITCH \
  --require-pretrade-pass \
  --require-risk-pass
```

Create `data/KILL_SWITCH` to block new plans immediately. Risk state is read from `--risk-state` when supplied and supports `date`, `orders`, `realized_loss`, and `pause_until`.
