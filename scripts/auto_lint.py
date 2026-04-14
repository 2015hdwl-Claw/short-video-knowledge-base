#!/usr/bin/env python3
"""Periodic lint automation. Usage: python3 scripts/auto_lint.py [--push]"""
import argparse, os, subprocess, sys
from datetime import datetime

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPTS = os.path.join(REPO, "scripts")
REPORT = os.path.join(REPO, "wiki", "lint-report.md")


def run(label, cmd):
    """Run a subprocess step, return True on success."""
    print(f"\n--- {label} ---")
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, cwd=REPO, timeout=300)
        for ln in r.stdout.strip().splitlines()[-5:]:
            print(f"  {ln}")
        if r.returncode != 0:
            print(f"  [FAIL] exit {r.returncode}")
            for ln in r.stderr.strip().splitlines()[-3:]:
                print(f"  STDERR: {ln}")
            return False
        print("  [PASS]"); return True
    except subprocess.TimeoutExpired:
        print("  [FAIL] timed out"); return False
    except Exception as e:
        print(f"  [FAIL] {e}"); return False


def auto_push():
    """Commit and push lint-report.md if it changed."""
    if not os.path.isfile(REPORT):
        return
    try:
        r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", REPORT],
                           cwd=REPO, capture_output=True, check=False)
        if r.returncode == 0:
            print("\n[push] Report unchanged."); return
        ts = datetime.now().strftime("%Y-%m-%d")
        subprocess.run(["git", "add", REPORT], cwd=REPO, check=True)
        subprocess.run(["git", "commit", "-m",
                        f"chore: auto lint report ({ts})"], cwd=REPO, check=True)
        subprocess.run(["git", "push"], cwd=REPO, check=True, timeout=60)
        print(f"\n[push] Pushed ({ts})")
    except Exception as e:
        print(f"\n[push] Error: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="Commit and push if changed")
    args = ap.parse_args()
    exe, ts = sys.executable, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"=== Lint run: {ts} ===\n  Repo: {REPO}")
    res = {}
    res["basic"] = run("[1/3] Basic lint", f'"{exe}" "{SCRIPTS}/lint_wiki.py"')
    if os.environ.get("CLASSIFIER_API_KEY"):
        res["semantic"] = run("[2/3] Semantic lint",
                              f'"{exe}" "{SCRIPTS}/lint_wiki.py" --semantic')
    else:
        print("\n--- [2/3] Semantic lint ---\n  [SKIP] No CLASSIFIER_API_KEY")
        res["semantic"] = None
    res["smoke"] = run("[3/3] Smoke test", f'"{exe}" "{SCRIPTS}/search.py" "AI" --limit 3')
    p = sum(1 for v in res.values() if v is True)
    f = sum(1 for v in res.values() if v is False)
    s = sum(1 for v in res.values() if v is None)
    print(f"\n{'='*40}\n  {p}/{p+f+s} passed, {f} failed, {s} skipped")
    for n, v in res.items():
        print(f"  - {n}: {'PASS' if v is True else 'FAIL' if v is False else 'SKIP'}")
    print(f"  Finished: {datetime.now().strftime('%H:%M:%S')}\n{'='*40}")
    if args.push:
        auto_push()
    sys.exit(0 if f == 0 else 1)


if __name__ == "__main__":
    main()
