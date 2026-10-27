"""RLS policies of the production schema, checked on a throwaway Postgres container.

Starts postgres:17-alpine with deploy/postgres/00_auth_shim.sql + chaoba/server/schema.sql + deploy/postgres/02_grants.sql
as init scripts (the same order docker-compose.yml uses), then runs deploy/rls_test.sql. Skips cleanly when Docker
is not installed or the daemon is not running. Opt out with CHAOBA_SKIP_DOCKER_TESTS=1.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE = os.environ.get("CHAOBA_PG_IMAGE", "postgres:17-alpine")


def _docker_ready() -> bool:
    if os.environ.get("CHAOBA_SKIP_DOCKER_TESTS") or not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not _docker_ready(), reason="Docker daemon not available")


def _run(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)


@pytest.fixture(scope="module")
def pg():
    name = f"chaoba-rls-{uuid.uuid4().hex[:8]}"
    mounts = [
        (ROOT / "deploy/postgres/00_auth_shim.sql", "/docker-entrypoint-initdb.d/00_auth_shim.sql"),
        (ROOT / "chaoba/server/schema.sql", "/docker-entrypoint-initdb.d/01_schema.sql"),
        (ROOT / "deploy/postgres/02_grants.sql", "/docker-entrypoint-initdb.d/02_grants.sql"),
        (ROOT / "deploy/rls_test.sql", "/deploy/rls_test.sql"),
    ]
    args = ["docker", "run", "-d", "--rm", "--name", name,
            "-e", "POSTGRES_USER=chaoba", "-e", "POSTGRES_PASSWORD=test", "-e", "POSTGRES_DB=chaoba"]
    for src, dst in mounts:
        args += ["-v", f"{src}:{dst}:ro"]
    started = _run(*args, IMAGE, timeout=300)
    if started.returncode != 0:
        pytest.skip(f"could not start {IMAGE}: {started.stderr.strip()[:200]}")
    try:
        # The entrypoint runs init scripts on a temporary server, then restarts; wait for the final server.
        deadline = time.time() + 120
        while time.time() < deadline:
            lg = _run("docker", "logs", name)
            if lg.returncode != 0:  # container exited (with --rm it is gone): an init script failed
                pytest.fail(f"Postgres container stopped during init: {lg.stderr.strip()[:500]}")
            logs = lg.stdout + lg.stderr
            if "init process complete" in logs:
                ok = _run("docker", "exec", name, "pg_isready", "-U", "chaoba", "-d", "chaoba", "-h", "127.0.0.1")
                if ok.returncode == 0:
                    break
            if "ERROR:" in logs:
                pytest.fail(f"schema init failed:\n{logs[-3000:]}")
            time.sleep(1)
        else:
            pytest.fail("Postgres did not become ready in 120 s")
        yield name
    finally:
        _run("docker", "rm", "-f", name)


def test_schema_applies_and_rls_policies_hold(pg):
    r = _run("docker", "exec", pg, "psql", "-U", "chaoba", "-d", "chaoba", "-v", "ON_ERROR_STOP=1",
             "-f", "/deploy/rls_test.sql")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RLS OK" in r.stdout


def test_no_audio_column_in_production_schema(pg):
    r = _run("docker", "exec", pg, "psql", "-U", "chaoba", "-d", "chaoba", "-At", "-c",
             "select table_name || '.' || column_name from information_schema.columns "
             "where table_schema = 'public' and (column_name ilike '%audio%' or column_name ilike '%recording%')")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""


def test_rls_enabled_on_every_table(pg):
    r = _run("docker", "exec", pg, "psql", "-U", "chaoba", "-d", "chaoba", "-At", "-c",
             "select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
             "where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", f"tables without RLS: {r.stdout.split()}"
