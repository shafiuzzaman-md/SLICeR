#!/usr/bin/env python3

import os
import subprocess
import sys
from pathlib import Path

CODEQL_CLI_REPO = "https://github.com/github/codeql-cli-binaries/releases/latest/download/codeql-linux64.zip"
CODEQL_CLI_DIR = os.path.expanduser("~/codeql-cli")
CODEQL_BIN = os.path.join(CODEQL_CLI_DIR, "codeql")

CODEQL_QUERIES_REPO = "https://github.com/github/codeql.git"
CODEQL_QUERIES_DIR = os.path.expanduser("~/LLMSE/codeql")


def run(cmd, cwd=None):
    print(f"[RUN] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def download_and_extract_codeql():
    print("[*] Downloading and installing CodeQL CLI...")
    if Path(CODEQL_BIN).exists():
        print(f"[!] CodeQL already installed at: {CODEQL_BIN}")
        return

    os.makedirs(CODEQL_CLI_DIR, exist_ok=True)
    zip_path = "/tmp/codeql.zip"
    run(["wget", "-O", zip_path, CODEQL_CLI_REPO])
    run(["unzip", "-o", zip_path, "-d", CODEQL_CLI_DIR])
    os.remove(zip_path)

    if not Path(CODEQL_BIN).exists():
        print("[!] Installation failed: codeql binary not found")
        sys.exit(1)

    print(f"[+] CodeQL CLI installed at: {CODEQL_BIN}")


def clone_queries_repo():
    print("[*] Cloning CodeQL query packs...")
    if Path(CODEQL_QUERIES_DIR).exists():
        print(f"[!] Query repo already exists: {CODEQL_QUERIES_DIR}")
        return

    run(["git", "clone", "--depth", "1", CODEQL_QUERIES_REPO, CODEQL_QUERIES_DIR])
    print(f"[+] CodeQL query packs cloned into: {CODEQL_QUERIES_DIR}")


def install_query_dependencies():
    print("[*] Installing CodeQL query pack dependencies...")
    for qlpack in ["cpp/ql", "cpp/queries"]:
        qlpack_path = Path(CODEQL_QUERIES_DIR) / qlpack
        if (qlpack_path / "qlpack.yml").exists():
            run([CODEQL_BIN, "pack", "install"], cwd=qlpack_path)
        else:
            print(f"[!] Skipped: No qlpack.yml in {qlpack_path}")


def configure_env():
    bashrc = Path.home() / ".bashrc"
    export_cmd = f'export CODEQL_CLI="{CODEQL_BIN}"'
    path_cmd = f'export PATH="$CODEQL_CLI:$PATH"'

    if bashrc.exists() and export_cmd in bashrc.read_text():
        print("[*] CODEQL_CLI already set in ~/.bashrc")
    else:
        print("[*] Setting environment variables in ~/.bashrc")
        with open(bashrc, "a") as f:
            f.write(f"\n# CodeQL setup\n{export_cmd}\n{path_cmd}\n")
        print("[+] Added CODEQL_CLI and PATH to ~/.bashrc")
        print("    Run `source ~/.bashrc` or restart your terminal.")

    os.environ["CODEQL_CLI"] = CODEQL_BIN
    print(f"[+] Environment variable set: CODEQL_CLI={CODEQL_BIN}")


def main():
    download_and_extract_codeql()
    clone_queries_repo()
    install_query_dependencies()
    configure_env()
    print("\n CodeQL setup complete. Try running:")
    print("   codeql --version")


if __name__ == "__main__":
    main()
