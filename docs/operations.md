# Operations

## Local setup

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e ".[dev,live]"
cp .env.example .env.local
```

## Background jobs

- `scripts/background_manager.sh start|status|stop` manages the local monitor loop.
- `scripts/rotate_data.sh`, `scripts/prune_data_artifacts.sh`, and `scripts/compact_data_caches.sh` keep runtime data bounded.

## Runtime locations

- `data/`: snapshots, reports, and generated JSONL artifacts.
- `var/`: PID files, logs, and supervisor state.
- `rules/`: checked-in rule caches and example rule files.

## GitHub upload checklist

1. Make sure `.env.local` is never staged.
2. Keep `data/` and `var/` out of the repository.
3. Run the test suite before pushing.
4. Avoid committing generated market data unless you explicitly want it tracked.
