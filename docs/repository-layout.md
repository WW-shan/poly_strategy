# Repository Layout

```text
poly_strategy/
├── poly_strategy/        core package
├── scripts/              orchestration and maintenance helpers
├── tests/                unit test suite
├── docs/                 architecture, operations, command reference
├── rules/                checked-in rule examples and caches
├── data/                 runtime artifacts (gitignored)
└── var/                  logs and PID state (gitignored)
```

## What belongs where

- Package logic goes in `poly_strategy/`.
- Recurring shell workflows go in `scripts/`.
- Public-facing explanations go in `docs/`.
- Generated snapshots, reports, and logs stay in `data/` and `var/`.
