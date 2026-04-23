#!/usr/bin/env python3
"""Periodic lint automation for the short-video knowledge base.

Usage:
    python3 scripts/auto_lint.py
    python3 scripts/auto_lint.py --push    # auto-commit + push if report changed
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPTS = os.path.join(REPO, "scripts")
REPORT_PATH = os.path.join(REPO, "wiki", "lint-report.md")


def run_step(label, cmd):
    """Run a subprocess step and return (success, output_lines)."""
    print(f"\n--- {label} ---")
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=REPO,
            timeout=300,
        )
        if result.stdout:
            for line in result.stdout.strip().splitlines()[-5:]:
                print(f"  {line}")
        if result.returncode != 0:
            print(f"  [FAIL] exit code {result.returncode}")
            if result.stderr:
                for line in result.stderr.strip().splitlines()[-3:]:
                    print(f"  STDERR: {line}")
            return False, result.returncode
        print("  [PASS]")
        return True, 0
    except subprocess.TimeoutExpired:
        print("  [FAIL] timed out after 300s")
        return False, -1
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False, -1


def auto_push_if_changed():
    """Git commit and push lint-report.md if it changed."""
    if not os.path.isfile(REPORT_PATH):
        print("\n[push] No lint-report.md found, nothing to push.")
        return

    try:
        subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", REPORT_PATH],
            cwd=REPO, capture_output=True, check=False,
        )
        # diff --quiet exits 0 if no diff, 1 if diff
        result = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", REPORT_PATH],
            cwd=REPO, capture_output=True, check=False,
        )
        if result.returncode == 0:
            print("\n[push] lint-report.md unchanged, skipping commit.")
            return

        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        subprocess.run(
            ["git", "add", REPORT_PATH], cwd=REPO, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"chore: auto lint report ({ts})"],
            cwd=REPO, check=True,
        )
        subprocess.run(
            ["git", "push"], cwd=REPO, check=True, timeout=60,
        )
        print(f"\n[push] Committed and pushed lint-report.md ({ts})")
    except subprocess.CalledProcessError as e:
        print(f"\n[push] Git error: {e}")
    except Exception as e:
        print(f"\n[push] Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Periodic lint automation")
    parser.add_argument("--push", action="store_true",
                        help="Auto-commit and push if lint-report.md changed")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"=== Lint run: {ts} ===")
    print(f"  Repo: {REPO}")

    results = {}

    # 1. Basic keyword lint
    ok, _ = run_step(
        "[1/3] Basic keyword lint",
        f'"{sys.executable}" "{SCRIPTS}/lint_wiki.py"',
    )
    results["basic_lint"] = ok

    # 2. Semantic lint (only if API key is set)
    if os.environ.get("CLASSIFIER_API_KEY"):
        ok, _ = run_step(
            "[2/3] Semantic LLM lint",
            f'"{sys.executable}" "{SCRIPTS}/lint_wiki.py" --semantic',
        )
        results["semantic_lint"] = ok
    else:
        print("\n--- [2/3] Semantic LLM lint ---")
        print("  [SKIP] CLASSIFIER_API_KEY not set")
        results["semantic_lint"] = None

    # 3. Smoke test: search
    ok, _ = run_step(
        "[3/3] Smoke test (search 'AI')",
        f'"{sys.executable}" "{SCRIPTS}/search.py" "AI" --limit 3',
    )
    results["smoke_test"] = ok

    # Summary
    passed = sum(1 for v in results.values() if v is True)
    failed = sum(1 for v in results.values() if v is False)
    skipped = sum(1 for v in results.values() if v is None)
    total = passed + failed + skipped

    print(f"\n{'='*40}")
    print(f"  Summary: {passed}/{total} passed, {failed} failed, {skipped} skipped")
    for name, status in results.items():
        icon = "PASS" if status is True else ("FAIL" if status is False else "SKIP")
        print(f"  - {name}: {icon}")
    print(f"  Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*40}")

    if args.push:
        auto_push_if_changed()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
