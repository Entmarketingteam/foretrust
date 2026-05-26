#!/usr/bin/env python3
"""Run Supabase migrations over the Management API (HTTPS).

Why not psql / supabase CLI: the Postgres pooler ports (5432/6543) are
firewall-blocked from some networks. The Management API runs DDL over
port 443, which is always reachable.

Usage:
    python migrate_supabase.py                      # run all supabase/migrations/*.sql
    python migrate_supabase.py path/to/file.sql ... # run specific files

Auth (first one found wins):
    1. SUPABASE_ACCESS_TOKEN env var (use this on Railway / CI)
    2. macOS Keychain "Supabase CLI" entry (local dev, set by `supabase login`)

Project ref (first one found wins):
    1. SUPABASE_PROJECT_REF env var
    2. parsed from SUPABASE_URL (https://<ref>.supabase.co)
    3. supabase/.temp/project-ref
"""
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"


def get_access_token() -> str:
    token = os.environ.get("SUPABASE_ACCESS_TOKEN")
    if token:
        return token.strip()
    # macOS Keychain fallback (go-keyring stores a base64 blob)
    try:
        raw = subprocess.check_output(
            ["security", "find-generic-password", "-s", "Supabase CLI", "-w"],
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise SystemExit(
            "No access token: set SUPABASE_ACCESS_TOKEN or run `supabase login`."
        )
    if raw.startswith("go-keyring-base64:"):
        raw = base64.b64decode(raw[len("go-keyring-base64:"):]).decode()
    return raw.strip()


def get_project_ref() -> str:
    ref = os.environ.get("SUPABASE_PROJECT_REF")
    if ref:
        return ref.strip()
    url = os.environ.get("SUPABASE_URL", "")
    m = re.match(r"https://([a-z0-9]+)\.supabase\.co", url)
    if m:
        return m.group(1)
    ref_file = REPO_ROOT / "supabase" / ".temp" / "project-ref"
    if ref_file.exists():
        return ref_file.read_text().strip()
    raise SystemExit(
        "No project ref: set SUPABASE_PROJECT_REF or SUPABASE_URL."
    )


def run_sql(ref: str, token: str, sql: str) -> None:
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{ref}/database/query",
        data=json.dumps({"query": sql}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            # Cloudflare fronts the API and 403s the default python-urllib UA
            "User-Agent": "foretrust-migrate/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        resp.read()  # 2xx = applied; body is the result set (ignored for DDL)


def main() -> None:
    args = sys.argv[1:]
    if args:
        files = [Path(a) for a in args]
    else:
        files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise SystemExit(f"No .sql files found in {MIGRATIONS_DIR}")

    ref = get_project_ref()
    token = get_access_token()
    print(f"Target project: {ref}")

    for f in files:
        if not f.exists():
            raise SystemExit(f"File not found: {f}")
        print(f"Applying {f.name} ...", end=" ", flush=True)
        try:
            run_sql(ref, token, f.read_text())
        except urllib.error.HTTPError as e:
            print("FAILED")
            raise SystemExit(f"  HTTP {e.code}: {e.read().decode()}")
        print("ok")

    print(f"Done. {len(files)} migration(s) applied.")


if __name__ == "__main__":
    main()
