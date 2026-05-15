#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RUNTIME_DIR="${RUNTIME_DIR:-var/run}"
LOG_DIR="${LOG_DIR:-var/log}"
PID_FILE="${PID_FILE:-$RUNTIME_DIR/poly_strategy-background.pid}"
MONITOR_PID_FILE="${MONITOR_PID_FILE:-$RUNTIME_DIR/poly_strategy-monitor.pid}"
SUPERVISOR_LOG="${SUPERVISOR_LOG:-$LOG_DIR/poly_strategy-background.log}"
TMUX_SESSION="${TMUX_SESSION:-poly_strategy_bg}"
COMMAND="${1:-status}"

mkdir -p "$RUNTIME_DIR" "$LOG_DIR"

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log() {
  echo "$(timestamp) $*"
}

pid_alive() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

read_pid_file() {
  local path="$1"
  [[ -s "$path" ]] && sed -n '1p' "$path" || true
}

file_sig() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "missing"
    return 0
  fi
  stat -f "%m:%z" "$path" 2>/dev/null || stat -c "%Y:%s" "$path"
}

load_env() {
  if [[ -f .env.local ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env.local
    set +a
  fi
  if [[ -n "${PROXY:-}" && -z "${HTTPS_PROXY:-}" ]]; then
    export HTTPS_PROXY="http://${PROXY}"
    export HTTP_PROXY="http://${PROXY}"
  fi
}

stop_pid() {
  local pid="$1"
  if ! pid_alive "$pid"; then
    return 0
  fi
  pkill -TERM -P "$pid" >/dev/null 2>&1 || true
  kill -TERM "$pid" >/dev/null 2>&1 || true
  for _ in {1..20}; do
    pid_alive "$pid" || return 0
    sleep 0.25
  done
  pkill -KILL -P "$pid" >/dev/null 2>&1 || true
  kill -KILL "$pid" >/dev/null 2>&1 || true
}

run_logged() {
  local name="$1"
  shift
  local log_path="$LOG_DIR/$name.log"
  log "job_start name=$name command=$*" >> "$SUPERVISOR_LOG"
  set +e
  "$@" >> "$log_path" 2>&1
  local status=$?
  set -e
  log "job_done name=$name status=$status log=$log_path" >> "$SUPERVISOR_LOG"
  return 0
}

start_monitor() {
  if [[ "${ENABLE_MONITOR:-1}" != "1" ]]; then
    return 0
  fi
  local existing
  existing="$(read_pid_file "$MONITOR_PID_FILE")"
  if pid_alive "$existing"; then
    return 0
  fi
  local monitor_log="${MONITOR_LOG:-$LOG_DIR/realtime-monitor.log}"
  (
    load_env
    export PYTHONUNBUFFERED=1
    export REPORT_OUT="${REPORT_OUT:-data/realtime-monitor-24h-v1.jsonl}"
    export SNAPSHOTS_OUT="${SNAPSHOTS_OUT:-data/realtime-monitor-24h-v1-snapshots.ndjson}"
    export LATEST_SNAPSHOTS_OUT="${LATEST_SNAPSHOTS_OUT:-data/realtime-monitor-24h-v1-latest-snapshots.ndjson}"
    export SNAPSHOT_INTERVAL="${SNAPSHOT_INTERVAL:-2}"
    export STALE_TIMEOUT="${STALE_TIMEOUT:-30}"
    export RECONNECT_DELAY="${RECONNECT_DELAY:-2}"
    export MIN_NET_EDGE="${MIN_NET_EDGE:-0.001}"
    export MAX_CAPITAL_PER_TRADE="${MAX_CAPITAL_PER_TRADE:-10}"
    export BANKROLL="${BANKROLL:-100}"
    export MIN_PAPER_ROI="${MIN_PAPER_ROI:-0.01}"
    export MIN_RUN_OBSERVATIONS="${MIN_RUN_OBSERVATIONS:-2}"
    export MIN_RUN_SECONDS="${MIN_RUN_SECONDS:-3}"
    export INCLUDE_TOP_MARKETS="${INCLUDE_TOP_MARKETS:-400}"
    export INCLUDE_TOP_NEG_RISK_GROUPS="${INCLUDE_TOP_NEG_RISK_GROUPS:-60}"
    export MAX_WATCHLIST_MARKETS="${MAX_WATCHLIST_MARKETS:-1000}"
    export EXTERNAL_SIGNALS="${EXTERNAL_SIGNALS:-data/external-signals.ndjson}"
    export WS_MAX_SIZE="${WS_MAX_SIZE:-4194304}"
    exec scripts/run_realtime_monitor.sh
  ) >> "$monitor_log" 2>&1 &
  local pid=$!
  echo "$pid" > "$MONITOR_PID_FILE"
  log "monitor_started pid=$pid log=$monitor_log" >> "$SUPERVISOR_LOG"
}

tmux_available() {
  command -v tmux >/dev/null 2>&1
}

restart_monitor() {
  local pid
  pid="$(read_pid_file "$MONITOR_PID_FILE")"
  if pid_alive "$pid"; then
    log "monitor_restart stopping_pid=$pid" >> "$SUPERVISOR_LOG"
    stop_pid "$pid"
  fi
  rm -f "$MONITOR_PID_FILE"
  start_monitor
}

start_supervisor_detached() {
  if tmux_available; then
    tmux kill-session -t "$TMUX_SESSION" >/dev/null 2>&1 || true
    tmux new-session -d -s "$TMUX_SESSION" /bin/zsh -lc "cd \"$ROOT_DIR\" && exec \"$ROOT_DIR/scripts/background_manager.sh\" run"
    for _ in {1..40}; do
      local existing
      existing="$(read_pid_file "$PID_FILE")"
      if pid_alive "$existing"; then
        return 0
      fi
      sleep 0.25
    done
    echo "failed to start tmux session" >&2
    return 1
  fi
  nohup "$0" run >> "$SUPERVISOR_LOG" 2>&1 < /dev/null &
  echo "$!" > "$PID_FILE"
}

stop_manager() {
  local manager_pid monitor_pid
  manager_pid="$(read_pid_file "$PID_FILE")"
  monitor_pid="$(read_pid_file "$MONITOR_PID_FILE")"
  if pid_alive "$monitor_pid"; then
    stop_pid "$monitor_pid"
  fi
  rm -f "$MONITOR_PID_FILE"
  if pid_alive "$manager_pid"; then
    stop_pid "$manager_pid"
  fi
  pkill -TERM -f 'poly_strategy\.cli (realtime-monitor-watchlist|collect-polymarket|discover-rules|paper-monitor)' >/dev/null 2>&1 || true
  sleep 0.5
  pkill -KILL -f 'poly_strategy\.cli (realtime-monitor-watchlist|collect-polymarket|discover-rules|paper-monitor)' >/dev/null 2>&1 || true
  rm -f "$PID_FILE"
}

case "$COMMAND" in
  start)
    existing="$(read_pid_file "$PID_FILE")"
    if pid_alive "$existing"; then
      echo "background_running pid=$existing"
      exit 0
    fi
    start_supervisor_detached
    sleep 1
    "$0" status
    ;;
  run)
    echo "$$" > "$PID_FILE"
    load_env
    trap 'restart_status=$?; monitor_pid="$(read_pid_file "$MONITOR_PID_FILE")"; if pid_alive "$monitor_pid"; then stop_pid "$monitor_pid"; fi; if pid_alive "${discovery_pid:-}"; then stop_pid "$discovery_pid"; fi; rm -f "$PID_FILE" "$MONITOR_PID_FILE"; exit "$restart_status"' INT TERM EXIT

    start_monitor

    ALERT_INTERVAL="${ALERT_INTERVAL:-60}"
    ANALYSIS_INTERVAL="${ANALYSIS_INTERVAL:-900}"
    ROTATION_INTERVAL="${ROTATION_INTERVAL:-300}"
    EXTERNAL_SIGNALS_INTERVAL="${EXTERNAL_SIGNALS_INTERVAL:-3600}"
    DISCOVERY_INTERVAL="${DISCOVERY_INTERVAL:-3600}"
    RULE_PROMOTION_INTERVAL="${RULE_PROMOTION_INTERVAL:-1800}"
    MAKER_SCAN_INTERVAL="${MAKER_SCAN_INTERVAL:-300}"
    MAKER_FILL_SIM_INTERVAL="${MAKER_FILL_SIM_INTERVAL:-900}"
    MAKER_ADAPTIVE_SIM_INTERVAL="${MAKER_ADAPTIVE_SIM_INTERVAL:-1800}"
    MAKER_HEDGE_SCAN_INTERVAL="${MAKER_HEDGE_SCAN_INTERVAL:-300}"
    MAKER_HEDGE_SIM_INTERVAL="${MAKER_HEDGE_SIM_INTERVAL:-900}"
    MAKER_HYBRID_SCAN_INTERVAL="${MAKER_HYBRID_SCAN_INTERVAL:-300}"
    MAKER_HYBRID_SIM_INTERVAL="${MAKER_HYBRID_SIM_INTERVAL:-900}"
    MAKER_HYBRID_TAPE_INTERVAL="${MAKER_HYBRID_TAPE_INTERVAL:-900}"
    CROSS_PLATFORM_SCAN_INTERVAL="${CROSS_PLATFORM_SCAN_INTERVAL:-1800}"
    SUCCESS_STATUS_INTERVAL="${SUCCESS_STATUS_INTERVAL:-60}"
    LOOP_SLEEP="${LOOP_SLEEP:-5}"

    ENABLE_ALERTS="${ENABLE_ALERTS:-1}"
    ENABLE_EXECUTION_DRY_RUN="${ENABLE_EXECUTION_DRY_RUN:-1}"
    ENABLE_NOTIFICATIONS="${ENABLE_NOTIFICATIONS:-0}"
    ENABLE_REALTIME_ANALYSIS="${ENABLE_REALTIME_ANALYSIS:-1}"
    ENABLE_DATA_ROTATION="${ENABLE_DATA_ROTATION:-1}"
    ENABLE_EXTERNAL_SIGNALS="${ENABLE_EXTERNAL_SIGNALS:-1}"
    ENABLE_DISCOVERY_REFRESH="${ENABLE_DISCOVERY_REFRESH:-1}"
    ENABLE_RULE_PROMOTION="${ENABLE_RULE_PROMOTION:-1}"
    ENABLE_MAKER_SCAN="${ENABLE_MAKER_SCAN:-1}"
    ENABLE_MAKER_FILL_SIM="${ENABLE_MAKER_FILL_SIM:-1}"
    ENABLE_MAKER_ADAPTIVE_SIM="${ENABLE_MAKER_ADAPTIVE_SIM:-1}"
    ENABLE_MAKER_HEDGE_SCAN="${ENABLE_MAKER_HEDGE_SCAN:-1}"
    ENABLE_MAKER_HEDGE_SIM="${ENABLE_MAKER_HEDGE_SIM:-1}"
    ENABLE_MAKER_HYBRID_SCAN="${ENABLE_MAKER_HYBRID_SCAN:-1}"
    ENABLE_MAKER_HYBRID_SIM="${ENABLE_MAKER_HYBRID_SIM:-1}"
    ENABLE_MAKER_HYBRID_TAPE="${ENABLE_MAKER_HYBRID_TAPE:-1}"
    ENABLE_CROSS_PLATFORM_SCAN="${ENABLE_CROSS_PLATFORM_SCAN:-1}"
    ENABLE_SUCCESS_STATUS="${ENABLE_SUCCESS_STATUS:-1}"

    WATCHLIST="${WATCHLIST:-data/watchlist-current.json}"
    RULES="${RULES:-data/gpt55-candidate-rules-all.json}"
    DATA_MAX_BYTES="${DATA_MAX_BYTES:-52428800}"

    next_alert=0
    next_analysis=0
    next_rotation=0
    next_external=0
    next_discovery=0
    next_promotion=0
    next_maker_scan=0
    next_maker_fill_sim=0
    next_maker_adaptive_sim=0
    next_maker_hedge_scan=0
    next_maker_hedge_sim=0
    next_maker_hybrid_scan=0
    next_maker_hybrid_sim=0
    next_maker_hybrid_tape=0
    next_cross_platform_scan=0
    next_success_status=0
    discovery_pid=""

    log "manager_started pid=$$" >> "$SUPERVISOR_LOG"
    while true; do
      start_monitor
      now="$(date +%s)"

      if [[ "$ENABLE_ALERTS" == "1" && "$now" -ge "$next_alert" ]]; then
        run_logged monitor-alerts scripts/run_monitor_alerts_once.sh
        if [[ "$ENABLE_EXECUTION_DRY_RUN" == "1" ]]; then
          run_logged execution-dry-run scripts/run_execution_dry_run_once.sh
        fi
        if [[ "$ENABLE_NOTIFICATIONS" == "1" ]]; then
          run_logged notify-alerts scripts/run_notify_alerts_once.sh
        fi
        next_alert=$((now + ALERT_INTERVAL))
      fi

      if [[ "$ENABLE_REALTIME_ANALYSIS" == "1" && "$now" -ge "$next_analysis" ]]; then
        run_logged realtime-analysis scripts/run_realtime_analysis_once.sh
        next_analysis=$((now + ANALYSIS_INTERVAL))
      fi

      if [[ "$ENABLE_EXTERNAL_SIGNALS" == "1" && "$now" -ge "$next_external" ]]; then
        run_logged external-signals scripts/refresh_external_signals.sh
        next_external=$((now + EXTERNAL_SIGNALS_INTERVAL))
      fi

      if [[ "$ENABLE_DISCOVERY_REFRESH" == "1" && "$now" -ge "$next_discovery" ]]; then
        if pid_alive "$discovery_pid"; then
          log "job_skip name=discovery-refresh reason=still_running pid=$discovery_pid" >> "$SUPERVISOR_LOG"
        else
          (
            before_sig="$(file_sig "$WATCHLIST")"
            run_logged discovery-refresh env RESTART_ON_CHANGE=0 LLM_COMMAND_TIMEOUT="${LLM_COMMAND_TIMEOUT:-600}" scripts/refresh_discovery_watchlist.sh
            after_sig="$(file_sig "$WATCHLIST")"
            if [[ "$before_sig" != "$after_sig" ]]; then
              restart_monitor
            fi
          ) &
          discovery_pid=$!
          log "job_background name=discovery-refresh pid=$discovery_pid" >> "$SUPERVISOR_LOG"
        fi
        next_discovery=$((now + DISCOVERY_INTERVAL))
      fi

      if [[ "$ENABLE_RULE_PROMOTION" == "1" && "$now" -ge "$next_promotion" ]]; then
        before_rules="$(file_sig "$RULES")"
        run_logged rule-promotion env REBUILD_WATCHLIST_ON_ADD=0 COMMAND_TIMEOUT="${COMMAND_TIMEOUT:-600}" scripts/run_rule_promotion_once.sh
        after_rules="$(file_sig "$RULES")"
        if [[ "$before_rules" != "$after_rules" ]]; then
          run_logged watchlist-after-promotion env SKIP_GAMMA=1 SKIP_LLM=1 RESTART_ON_CHANGE=0 scripts/refresh_discovery_watchlist.sh
          restart_monitor
        fi
        next_promotion=$((now + RULE_PROMOTION_INTERVAL))
      fi

      if [[ "$ENABLE_MAKER_SCAN" == "1" && "$now" -ge "$next_maker_scan" ]]; then
        run_logged maker-scan scripts/run_maker_scan_once.sh
        next_maker_scan=$((now + MAKER_SCAN_INTERVAL))
      fi

      if [[ "$ENABLE_MAKER_FILL_SIM" == "1" && "$now" -ge "$next_maker_fill_sim" ]]; then
        run_logged maker-fill-sim scripts/run_maker_fill_sim_once.sh
        next_maker_fill_sim=$((now + MAKER_FILL_SIM_INTERVAL))
      fi

      if [[ "$ENABLE_MAKER_ADAPTIVE_SIM" == "1" && "$now" -ge "$next_maker_adaptive_sim" ]]; then
        run_logged maker-adaptive-sim scripts/run_maker_adaptive_sim_once.sh
        next_maker_adaptive_sim=$((now + MAKER_ADAPTIVE_SIM_INTERVAL))
      fi

      if [[ "$ENABLE_MAKER_HEDGE_SCAN" == "1" && "$now" -ge "$next_maker_hedge_scan" ]]; then
        run_logged maker-hedge-scan scripts/run_maker_hedge_scan_once.sh
        next_maker_hedge_scan=$((now + MAKER_HEDGE_SCAN_INTERVAL))
      fi

      if [[ "$ENABLE_MAKER_HEDGE_SIM" == "1" && "$now" -ge "$next_maker_hedge_sim" ]]; then
        run_logged maker-hedge-sim scripts/run_maker_hedge_sim_once.sh
        next_maker_hedge_sim=$((now + MAKER_HEDGE_SIM_INTERVAL))
      fi

      if [[ "$ENABLE_MAKER_HYBRID_SCAN" == "1" && "$now" -ge "$next_maker_hybrid_scan" ]]; then
        run_logged maker-hybrid-scan scripts/run_maker_hybrid_scan_once.sh
        next_maker_hybrid_scan=$((now + MAKER_HYBRID_SCAN_INTERVAL))
      fi

      if [[ "$ENABLE_MAKER_HYBRID_SIM" == "1" && "$now" -ge "$next_maker_hybrid_sim" ]]; then
        run_logged maker-hybrid-sim scripts/run_maker_hybrid_sim_once.sh
        next_maker_hybrid_sim=$((now + MAKER_HYBRID_SIM_INTERVAL))
      fi

      if [[ "$ENABLE_MAKER_HYBRID_TAPE" == "1" && "$now" -ge "$next_maker_hybrid_tape" ]]; then
        run_logged maker-hybrid-tape scripts/run_maker_hybrid_tape_once.sh
        next_maker_hybrid_tape=$((now + MAKER_HYBRID_TAPE_INTERVAL))
      fi

      if [[ "$ENABLE_CROSS_PLATFORM_SCAN" == "1" && "$now" -ge "$next_cross_platform_scan" ]]; then
        run_logged cross-platform-scan scripts/run_cross_platform_scan_once.sh
        next_cross_platform_scan=$((now + CROSS_PLATFORM_SCAN_INTERVAL))
      fi

      if [[ "$ENABLE_SUCCESS_STATUS" == "1" && "$now" -ge "$next_success_status" ]]; then
        run_logged success-status scripts/run_success_status_once.sh
        next_success_status=$((now + SUCCESS_STATUS_INTERVAL))
      fi

      if [[ "$ENABLE_DATA_ROTATION" == "1" && "$now" -ge "$next_rotation" ]]; then
        run_logged data-rotation env DATA_DIR=data MAX_BYTES="$DATA_MAX_BYTES" RETENTION_DAYS=7 INCLUDE_REPORTS=1 scripts/rotate_data.sh
        run_logged data-prune env DATA_DIR=data DATED_CACHE_RETENTION_DAYS=7 GZIP_RETENTION_DAYS=7 scripts/prune_data_artifacts.sh
        run_logged data-compact env GAMMA=data/polymarket-gamma.ndjson EXTERNAL_SIGNALS=data/external-signals.ndjson MAX_EXTERNAL_SIGNAL_LINES=2000 scripts/compact_data_caches.sh
        next_rotation=$((now + ROTATION_INTERVAL))
      fi

      sleep "$LOOP_SLEEP"
    done
    ;;
  stop)
    stop_manager
    if tmux_available; then
      tmux kill-session -t "$TMUX_SESSION" >/dev/null 2>&1 || true
    fi
    echo "background_stopped"
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  status)
    manager_pid="$(read_pid_file "$PID_FILE")"
    monitor_pid="$(read_pid_file "$MONITOR_PID_FILE")"
    if pid_alive "$manager_pid"; then
      echo "manager=running pid=$manager_pid"
    else
      echo "manager=stopped"
    fi
    if pid_alive "$monitor_pid"; then
      echo "monitor=running pid=$monitor_pid"
    else
      echo "monitor=stopped"
    fi
    if tmux_available && tmux has-session -t "$TMUX_SESSION" >/dev/null 2>&1; then
      echo "tmux_session=running name=$TMUX_SESSION"
    else
      echo "tmux_session=stopped name=$TMUX_SESSION"
    fi
    ;;
  tail)
    if tmux_available && tmux has-session -t "$TMUX_SESSION" >/dev/null 2>&1; then
      exec tmux attach -t "$TMUX_SESSION"
    fi
    tail -n "${TAIL_LINES:-120}" -f "$SUPERVISOR_LOG"
    ;;
  *)
    echo "usage: $0 {start|stop|restart|status|tail}" >&2
    exit 2
    ;;
esac
