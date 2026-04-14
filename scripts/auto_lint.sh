#!/usr/bin/env bash
# auto_lint.sh — Convenience wrapper for periodic lint automation
# Usage: ./scripts/auto_lint.sh
# Cron:  0 6 * * * cd /path/to/repo && ./scripts/auto_lint.sh >> /tmp/lint.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_DIR"
echo "=== Lint run: $(date -Iseconds) ==="

# 1. Basic keyword lint
echo "--- [1/3] Basic keyword lint ---"
if python3 scripts/lint_wiki.py; then
    echo "[PASS] Basic lint OK"
else
    echo "[FAIL] Basic lint exited with code $?"
fi

# 2. Semantic lint (only if API key is set)
echo "--- [2/3] Semantic lint ---"
if [ -n "${CLASSIFIER_API_KEY:-}" ]; then
    if python3 scripts/lint_wiki.py --semantic; then
        echo "[PASS] Semantic lint OK"
    else
        echo "[FAIL] Semantic lint exited with code $?"
    fi
else
    echo "[SKIP] CLASSIFIER_API_KEY not set, skipping semantic lint"
fi

# 3. Smoke test: search for "AI"
echo "--- [3/3] Smoke test (search 'AI') ---"
if python3 scripts/search.py "AI" --limit 3; then
    echo "[PASS] Search smoke test OK"
else
    echo "[FAIL] Search smoke test exited with code $?"
fi

echo "=== Lint complete: $(date -Iseconds) ==="
