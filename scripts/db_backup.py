"""Back up the development database and prove the backup restores.

    python -m scripts.db_backup backup            # dump + manifest (row counts, sha256)
    python -m scripts.db_backup verify [DUMP]     # restore into a throwaway container, compare

`backup` runs `pg_dump -Fc` inside the database container (read-only for the database) and
writes `.local/backups/<name>.dump` plus `<name>.manifest.json` (git-ignored). `verify` starts a
disposable `pgvector` container with no volume on 127.0.0.1:5434, restores the dump, checks that
every table's row count, the Alembic revision and the key/constraint count match the manifest,
then removes the container. It never touches the live database or its volume.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUPS = ROOT / ".local/backups"
LIVE = "concepttrail-postgres"
DISPOSABLE = "ct-restore-verify"
IMAGE = "pgvector/pgvector:0.8.7-pg18-trixie"
SCHEMA = "concepttrail"


def run(*args: str, input_bytes: bytes | None = None, check: bool = True) -> bytes:
    done = subprocess.run(args, input=input_bytes, capture_output=True, check=False)
    if check and done.returncode != 0:
        raise RuntimeError(
            f"{args[0]} {args[1] if len(args) > 1 else ''} failed: "
            f"{done.stderr.decode(errors='replace')[-400:]}"
        )
    return done.stdout


def env(container: str, name: str) -> str:
    return run("docker", "exec", container, "printenv", name).decode().strip()


def psql(container: str, user: str, db: str, sql: str) -> list[str]:
    out = run("docker", "exec", container, "psql", "-U", user, "-d", db, "-At", "-c", sql)
    return [line for line in out.decode().splitlines() if line]


def snapshot(container: str, user: str, db: str) -> dict:
    tables = psql(
        container,
        user,
        db,
        f"SELECT table_name FROM information_schema.tables WHERE table_schema = '{SCHEMA}' "
        "AND table_type = 'BASE TABLE' ORDER BY 1",
    )
    counts = {
        t: int(psql(container, user, db, f'SELECT count(*) FROM {SCHEMA}."{t}"')[0]) for t in tables
    }
    return {
        "tables": counts,
        "alembic": psql(container, user, db, "SELECT version_num FROM public.alembic_version"),
        "keys_and_constraints": int(
            psql(
                container,
                user,
                db,
                "SELECT count(*) FROM pg_constraint WHERE connamespace = "
                f"'{SCHEMA}'::regnamespace AND contype IN ('p','f','u','c')",
            )[0]
        ),
    }


def backup() -> Path:
    user, db = env(LIVE, "POSTGRES_USER"), env(LIVE, "POSTGRES_DB")
    BACKUPS.mkdir(parents=True, exist_ok=True)
    name = f"{db}_{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    before = snapshot(LIVE, user, db)
    dump = run(
        "docker", "exec", LIVE, "pg_dump", "-U", user, "-d", db, "-Fc", "-n", SCHEMA, "-n", "public"
    )
    path = BACKUPS / f"{name}.dump"
    path.write_bytes(dump)
    manifest = {
        "dump": path.name,
        "sha256": hashlib.sha256(dump).hexdigest(),
        "bytes": len(dump),
        "created_at": datetime.now(UTC).isoformat(),
        "source": {"container": LIVE, "database": db, "schemas": [SCHEMA, "public"]},
        **before,
    }
    (BACKUPS / f"{name}.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {
                "dump": str(path.relative_to(ROOT)),
                "sha256": manifest["sha256"],
                "tables": len(before["tables"]),
            }
        )
    )
    return path


def verify(dump_path: Path) -> int:
    manifest = json.loads(dump_path.with_suffix(".manifest.json").read_text())
    data = dump_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest["sha256"]:
        print("FAIL: dump checksum does not match its manifest")
        return 1
    run("docker", "rm", "-f", DISPOSABLE, check=False)
    run(
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        DISPOSABLE,
        "-e",
        "POSTGRES_USER=verify",
        "-e",
        f"POSTGRES_PASSWORD={secrets.token_urlsafe(18)}",
        "-e",
        "POSTGRES_DB=restore",
        "-p",
        "127.0.0.1:5434:5432",
        IMAGE,
    )
    try:
        for _ in range(60):
            ok = (
                subprocess.run(
                    ["docker", "exec", DISPOSABLE, "pg_isready", "-U", "verify", "-d", "restore"],
                    capture_output=True,
                ).returncode
                == 0
            )
            if ok:
                break
            time.sleep(1)
        time.sleep(1)
        psql(DISPOSABLE, "verify", "restore", "CREATE EXTENSION IF NOT EXISTS vector")
        toc = run("docker", "exec", "-i", DISPOSABLE, "pg_restore", "-l", input_bytes=data)
        keep = b"\n".join(line for line in toc.splitlines() if b" SCHEMA - public " not in line)
        run("docker", "exec", "-i", DISPOSABLE, "sh", "-c", "cat > /tmp/toc.list", input_bytes=keep)
        run("docker", "exec", "-i", DISPOSABLE, "sh", "-c", "cat > /tmp/b.dump", input_bytes=data)
        run(
            "docker",
            "exec",
            DISPOSABLE,
            "pg_restore",
            "-U",
            "verify",
            "-d",
            "restore",
            "--no-owner",
            "--exit-on-error",
            "-L",
            "/tmp/toc.list",
            "/tmp/b.dump",
        )
        after = snapshot(DISPOSABLE, "verify", "restore")
    finally:
        run("docker", "rm", "-f", DISPOSABLE, check=False)
    problems = [
        f"{t}: manifest {n}, restored {after['tables'].get(t)}"
        for t, n in manifest["tables"].items()
        if after["tables"].get(t) != n
    ]
    if after["alembic"] != manifest["alembic"]:
        problems.append(f"alembic: {manifest['alembic']} vs {after['alembic']}")
    if after["keys_and_constraints"] != manifest["keys_and_constraints"]:
        problems.append("constraint count differs")
    print(
        json.dumps(
            {
                "dump": dump_path.name,
                "tables": len(after["tables"]),
                "rows": sum(after["tables"].values()),
                "problems": problems,
            }
        )
    )
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.db_backup")
    parser.add_argument("command", choices=("backup", "verify"))
    parser.add_argument("dump", nargs="?", type=Path)
    args = parser.parse_args(argv)
    if args.command == "backup":
        backup()
        return 0
    dump = args.dump or max(BACKUPS.glob("*.dump"), key=lambda p: p.stat().st_mtime)
    return verify(dump)


if __name__ == "__main__":
    sys.exit(main())
