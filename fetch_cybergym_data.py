#!/usr/bin/env python3
"""
fetch_cybergym_data.py

Clone/update the CyberGym dataset locally and materialize ONLY the requested tasks
using sparse-checkout and selective Git-LFS fetch (so downloads stay minimal).

Examples:
  # Put repo in ./cybergym_data and fetch arvo:66502 and arvo:62911
  python3 fetch_cybergym_data.py --repo-dir ./cybergym_data arvo:66502 arvo:62911

  # Use default ./cybergym_data and fetch an OSS-Fuzz task too
  python3 fetch_cybergym_data.py arvo:66502 oss-fuzz:42535201
"""

from __future__ import annotations
import argparse
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple

HF_REPO_URL = "https://huggingface.co/datasets/sunblaze-ucb/cybergym"

def run(cmd: List[str], check: bool = True, env: dict | None = None):
    print(f"[RUN] {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, env=env)

def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None

def parse_task(t: str) -> Tuple[str, str]:
    if ":" not in t:
        raise SystemExit(f"Bad task format: {t}. Use ns:id (e.g., arvo:66502)")
    ns, tid = t.split(":", 1)
    if ns not in ("arvo", "oss-fuzz"):
        raise SystemExit(f"Unsupported namespace: {ns}")
    return ns, tid

def task_path(ns: str, tid: str) -> str:
    return f"data/{ns}/{tid}"

def ensure_repo(repo_dir: Path) -> Path:
    """Clone (blobless, no LFS smudge) if missing; otherwise update and set LFS skip-smudge."""
    repo_dir = repo_dir.resolve()
    if not have("git"):
        raise SystemExit("git not found. Please install git.")
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    if not repo_dir.exists():
        # Minimal clone: no blobs; do not download LFS on checkout
        env = os.environ.copy()
        env["GIT_LFS_SKIP_SMUDGE"] = "1"
        run(["git", "clone", "--filter=blob:none", "--no-checkout", HF_REPO_URL, str(repo_dir)], env=env)
        # Prepare main branch checkout (still blobless)
        run(["git", "-C", str(repo_dir), "checkout", "main"], env=env, check=False)
        # Enable LFS but keep skipSmudge true so future checkouts don't auto-download
        run(["git", "-C", str(repo_dir), "lfs", "install"], check=False)
        run(["git", "-C", str(repo_dir), "config", "lfs.skipSmudge", "true"], check=False)
        # Enable sparse-checkout in cone mode
        run(["git", "-C", str(repo_dir), "sparse-checkout", "init", "--cone"], check=False)
        # Start with the top-level data/ (empty set is allowed but data/ is convenient)
        run(["git", "-C", str(repo_dir), "sparse-checkout", "set", "data"], check=False)
    else:
        # Existing repo: ensure it's the right remote and up to date (no smudge)
        run(["git", "-C", str(repo_dir), "remote", "set-url", "origin", HF_REPO_URL], check=False)
        env = os.environ.copy()
        env["GIT_LFS_SKIP_SMUDGE"] = "1"
        run(["git", "-C", str(repo_dir), "fetch", "--all"], env=env, check=False)
        run(["git", "-C", str(repo_dir), "pull", "--ff-only"], env=env, check=False)
        run(["git", "-C", str(repo_dir), "lfs", "install"], check=False)
        run(["git", "-C", str(repo_dir), "config", "lfs.skipSmudge", "true"], check=False)
        # Make sure sparse-checkout is enabled
        run(["git", "-C", str(repo_dir), "sparse-checkout", "init", "--cone"], check=False)

    return repo_dir

def extend_sparse_paths(repo_dir: Path, paths: List[str]) -> None:
    """Union-update sparse-checkout with the given paths."""
    # Read current sparse list (ignore if none yet)
    try:
        cur = subprocess.run(
            ["git", "-C", str(repo_dir), "sparse-checkout", "list"],
            check=True, capture_output=True, text=True
        ).stdout.strip().splitlines()
    except subprocess.CalledProcessError:
        cur = []
    wanted = sorted(set(cur + paths))
    # 'set' with all paths at once (idempotent)
    run(["git", "-C", str(repo_dir), "sparse-checkout", "set", *wanted], check=False)

def materialize_tasks(repo_dir: Path, tasks: List[Tuple[str, str]]) -> None:
    """Fetch only LFS for the requested subpaths, then checkout those paths."""
    # Build include pattern for LFS fetch
    includes = [f"{task_path(ns, tid)}/**" for (ns, tid) in tasks]
    includes_arg = ",".join(includes)

    # Ensure directories exist for checkout to write into
    for ns, _ in tasks:
        (repo_dir / "data" / ns).mkdir(parents=True, exist_ok=True)

    # 1) Extend sparse-checkout to only the needed task folders (union with existing)
    extend_sparse_paths(repo_dir, [task_path(ns, tid) for (ns, tid) in tasks])

    # 2) Fetch ONLY the LFS blobs we’ll need
    run(["git", "-C", str(repo_dir), "lfs", "fetch", "--include", includes_arg, "--exclude", ""], check=False)

    # 3) Checkout files in those paths (won’t smudge due to skipSmudge=true)
    for ns, tid in tasks:
        p = task_path(ns, tid)
        run(["git", "-C", str(repo_dir), "checkout", "--", p], check=False)

    # 4) Now replace LFS pointers with actual content in just those paths
    for ns, tid in tasks:
        p = task_path(ns, tid)
        run(["git", "-C", str(repo_dir), "lfs", "checkout", p], check=False)
        print(f"[OK] Materialized {p}")

def main():
    ap = argparse.ArgumentParser(description="Fetch specific CyberGym tasks locally via sparse checkout + Git-LFS.")
    ap.add_argument("tasks", nargs="+", help="Tasks like arvo:66502 or oss-fuzz:42535201")
    ap.add_argument("--repo-dir", default="./cybergym_data", help="Local clone directory (default: ./cybergym_data)")
    args = ap.parse_args()

    repo_dir = ensure_repo(Path(args.repo_dir))
    parsed = [parse_task(t) for t in args.tasks]
    materialize_tasks(repo_dir, parsed)

    print("\n[OK] Done. Your data root for extract script is:")
    print(f"  {repo_dir}/data")
    print("Tip: Verify sizes with:\n  find "
          + " ".join(f"{task_path(ns, tid)}" for ns, tid in parsed)
          + " -maxdepth 1 -type f -printf \"%P\\t%k KB\\n\" | sort")

if __name__ == "__main__":
    main()
