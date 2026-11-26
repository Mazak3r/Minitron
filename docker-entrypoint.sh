#!/usr/bin/env bash
set -euo pipefail

mode="${1:-core}"
shift || true

case "$mode" in
  core)
    echo "[entrypoint] starting Laravel backend (php-fpm/artisan)…"
    # exec php-fpm OR artisan serve / supervisor / etc.
    exec "$@"
    ;;
  streamlit)
    echo "[entrypoint] starting Streamlit tools…"
    exec streamlit run /app/tools/app.py --server.port=8501 --server.address=0.0.0.0 "$@"
    ;;
  *)
    echo "[entrypoint] unknown mode: $mode" >&2
    exit 64
    ;;
esac
