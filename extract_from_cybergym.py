#!/usr/bin/env python3
"""
extract_from_cybergym.py

Minimal extractor: copies ONLY source trees from task images to a tidy dataset/
layout. No metadata handling.

Copies:
  • /src/<project> → ./dataset/<id>/<project>_<id>_{vul,fix}

Usage:
  python3 extract_from_cybergym.py arvo:66502 libxml2
  # Optional: choose output root
  python3 extract_from_cybergym.py arvo:66502 libxml2 --out-root ./my_datasets
"""

from __future__ import annotations
import argparse
import os
import shutil
import subprocess
from pathlib import Path
from typing import List

# ---------- shell helpers ----------
def run(cmd: List[str], check: bool = True, quiet: bool = False):
    if not quiet:
        print(f"[RUN] {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)

def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None

def ensure_docker():
    if not have("docker"):
        raise SystemExit("docker not found. Install Docker Engine and retry.")
    if subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        raise SystemExit("Docker daemon not reachable. Start Docker and retry.")

# ---------- docker helpers ----------
def docker_pull(image: str):
    run(["docker", "pull", image])

def docker_rm(name: str):
    subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def docker_create(name: str, image: str):
    docker_rm(name)
    run(["docker", "create", "--name", name, image, "/bin/true"])

def docker_cp_dir(name: str, src_dir: str, host_dst: Path) -> bool:
    if host_dst.exists():
        shutil.rmtree(host_dst)
    host_dst.parent.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(["docker", "cp", f"{name}:{src_dir}", str(host_dst)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if cp.returncode != 0:
        if host_dst.exists() and not any(host_dst.iterdir()):
            shutil.rmtree(host_dst, ignore_errors=True)
        return False
    try:
        run(["chown", "-R", f"{os.getuid()}:{os.getgid()}", str(host_dst)], check=False, quiet=True)
    except Exception:
        pass
    return True

# ---------- namespace → image repo ----------
def repo_for(ns: str) -> str:
    if ns == "arvo":
        return "n132/arvo"
    if ns == "oss-fuzz":
        return "cybergym/oss-fuzz-task"
    raise SystemExit(f"Unsupported namespace: {ns}")

# ---------- CodeQL-friendly build.sh (installed into each src tree) ----------
CODEQL_BUILD_SH = r"""#!/usr/bin/env bash
set -euo pipefail

ROOT="$(pwd)"
PREFIX="$ROOT/_inst"
BUILD_DIR="$ROOT/build"
NPROC="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)"

echo "[codeql-build] Root: $ROOT"
echo "[codeql-build] Prefix: $PREFIX"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing: $1"; exit 2; }; }

if [ -f "configure.ac" ] || [ -f "configure.in" ] || [ -f "autogen.sh" ]; then
  need autoreconf
  if ! command -v libtoolize >/dev/null 2>&1 && ! command -v libtool >/dev/null 2>&1; then
    echo "Missing: libtool (or libtoolize)"; exit 2
  fi
  need automake
  need pkg-config
fi

mkdir -p "$BUILD_DIR" "$PREFIX"

if [ -f "CMakeLists.txt" ]; then
  echo "[codeql-build] CMake project detected"
  cmake -S . -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_C_COMPILER="${CC:-cc}" -DCMAKE_CXX_COMPILER="${CXX:-c++}" \
        -DCMAKE_INSTALL_PREFIX="$PREFIX"
  cmake --build "$BUILD_DIR" -j"$NPROC" || true
  cmake --install "$BUILD_DIR" || true
else
  echo "[codeql-build] Autotools/Make project assumed"
  if [ -f "autogen.sh" ]; then
    ./autogen.sh || true
  elif [ ! -f "configure" ] && { [ -f "configure.ac" ] || [ -f "configure.in" ]; }; then
    autoreconf -fi || true
  fi
  if [ -f "configure" ]; then
    CC=${CC:-gcc} ./configure --without-python --prefix="$PREFIX" || true
  fi
  make -j"$NPROC" || true
  make install || true
fi

cat > "$BUILD_DIR/_probe.c" <<'EOF'
#include <stdio.h>
#ifdef __has_include
# if __has_include(<libxml/parser.h>)
#  include <libxml/parser.h>
# endif
#endif
int main() {
#ifdef LIBXML_TEST_VERSION
  xmlInitParser();
  xmlCleanupParser();
#endif
  puts("probe");
  return 0;
}
EOF

if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists libxml-2.0 2>/dev/null; then
  cc $(pkg-config --cflags libxml-2.0) "$BUILD_DIR/_probe.c" \
     $(pkg-config --libs libxml-2.0) -o "$BUILD_DIR/_probe" || true
else
  cc -I"$PREFIX/include" -I"$PREFIX/include/libxml2" \
     -L"$PREFIX/lib" "$BUILD_DIR/_probe.c" \
     -lxml2 -o "$BUILD_DIR/_probe" || true
fi

echo "[codeql-build] Done."
"""

def install_codeql_build_sh(dst_dirs: list[Path]) -> None:
    for d in dst_dirs:
        d.mkdir(parents=True, exist_ok=True)
        target = d / "build.sh"
        target.write_text(CODEQL_BUILD_SH, encoding="utf-8")
        try:
            os.chmod(target, 0o755)
        except Exception:
            pass
        print(f"[INFO] CodeQL build.sh written to {target}")

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Extract vulnerable/fixed sources from a single task (no metadata).")
    ap.add_argument("task", help="Task id: arvo:<id> or oss-fuzz:<id> (e.g., arvo:66502)")
    ap.add_argument("project", help="Project name under /src (e.g., libxml2)")
    ap.add_argument("--out-root", default="./dataset",
                    help="Directory under which to save extracted outputs (default: ./dataset)")
    args = ap.parse_args()

    if ":" not in args.task:
        raise SystemExit("Task must be in the form 'arvo:<id>' or 'oss-fuzz:<id>'")
    ns, tid = args.task.split(":", 1)

    ensure_docker()
    repo = repo_for(ns)
    vul_img, fix_img = f"{repo}:{tid}-vul", f"{repo}:{tid}-fix"
    vul_name, fix_name = f"{ns}_{tid}_vul", f"{ns}_{tid}_fix"

    for img in [vul_img, fix_img]:
        docker_pull(img)
    docker_create(vul_name, vul_img)
    docker_create(fix_name, fix_img)

    out_root = Path(args.out_root).expanduser().resolve()
    base_dir = out_root / tid
    base_dir.mkdir(parents=True, exist_ok=True)

    vul_out = base_dir / f"{args.project}_{tid}_vul"
    fix_out = base_dir / f"{args.project}_{tid}_fix"
    src_path = f"/src/{args.project}"

    got_vul = docker_cp_dir(vul_name, src_path, vul_out)
    got_fix = docker_cp_dir(fix_name, src_path, fix_out)

    if not got_vul or not got_fix:
        print("[INFO] One or both images lack /src/<project>; copied what was available.")

    # Install CodeQL build.sh into present trees
    install_codeql_build_sh([d for d in [vul_out, fix_out] if d.exists()])

    # Cleanup containers
    for n in [vul_name, fix_name]:
        docker_rm(n)

    print("\n[OK] Done.")
    print(f"  Output root: {base_dir}")
    if vul_out.exists(): print(f"  Vulnerable: {vul_out}")
    if fix_out.exists(): print(f"  Fixed     : {fix_out}")
    print("  Tip       : run ./build.sh inside each directory to build (autoconf/automake/libtool/pkg-config may be required)")

if __name__ == "__main__":
    main()
