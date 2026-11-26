#!/usr/bin/env python3
"""Windows/no-bash twin of scripts/deploy_all.sh: same L2 order, through the Snowflake Python connector.

  python scripts/deploy_local.py --connection <name> [--from <file>] [--skip-apps]

Uses a connection from ~/.snowflake/config.toml (no secrets in this file) and caches the MFA token, so one
approval covers the whole deploy. Files marked organizer may fail; they are reported and the deploy carries on.
"""
from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path

import snowflake.connector

ROOT = Path(__file__).resolve().parents[1]
APP_STAGE = "@SR_DB.APP.STREAMLIT_SRC"
APPS = [  # (object, main file, owner role, title)
    ("SR_DB.APP.CHIPPY", "streamlit_app.py", "SR_UI", "Chippy"),
    ("SR_DB.APP.CHIPPY_ADMIN", "admin_app.py", "SR_APP", "Chippy admin"),
]
APP_FILES = ["environment.yml", "pyproject.toml", ".streamlit/config.toml", "pages/*.py", "sr_ui/*.py"]


def plan() -> list[tuple[str, str]]:
    """(step, kind) in deploy_all.sh order. kind: '' required, 'organizer' optional, or a built-in step."""
    s = [("sql/00_setup/001_roles_wh_db.sql", "organizer"), ("sql/00_setup/002_settings.sql", ""),
         ("sql/00_setup/003_ops_tables.sql", ""), ("tests/sql/000_fixtures.sql", "")]
    s += [(str(p.relative_to(ROOT)).replace("\\", "/"), "") for d in ("sql/10_src", "sql/20_core")
          for p in sorted((ROOT / d).glob("*.sql"))]
    s += [("sql/40_app/401_result_tables.sql", ""), ("sr_lib", "put_sr_lib")]
    s += [(f"sql/30_ml/{p.name}", "") for p in sorted((ROOT / "sql/30_ml").glob("*.sql"))]
    s += [(f"sql/40_app/{p.name}", "") for p in sorted((ROOT / "sql/40_app").glob("*.sql"))
          if not p.name.startswith("401_")]
    s += [("sql/50_sem/501_v_sem_views.sql", ""), ("sql/50_sem/502_sv_share.sql", ""),
          ("sql/50_sem/503_kb_and_search.sql", ""), ("kb", "load_kb"), ("sql/50_sem/504_agent.sql", ""),
          ("sql/50_sem/505_cowork.sql", "organizer"), ("sql/50_sem/506_analyst_agent.sql", ""),
          ("sql/70_sec/701_grants.sql", "organizer"),
          ("sql/70_sec/704_app_agent.sql", ""), ("sql/70_sec/705_analyst_agent.sql", ""),
          ("sql/60_ops/601_stream_task.sql", ""), ("sql/60_ops/602_replay.sql", ""),
          ("sql/60_ops/603_notifications.sql", "organizer"), ("sql/60_ops/604_alert.sql", ""),
          ("sql/60_ops/606_observability.sql", ""), ("sql/70_sec/702_row_access.sql", ""),
          ("streamlit", "apps"), ("sql/70_sec/703_app_usage.sql", "")]
    return s


def run_file(conn, rel: str) -> None:
    text = (ROOT / rel).read_text(encoding="utf-8")
    for cur in conn.execute_stream(io.StringIO(text), remove_comments=True):
        cur.close()


def put_sr_lib(conn) -> None:
    build = ROOT / "python" / "build"
    build.mkdir(parents=True, exist_ok=True)
    zpath = build / "sr_lib.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted((ROOT / "python" / "sr_lib").rglob("*.py")):
            z.write(p, p.relative_to(ROOT / "python").as_posix())
    cur = conn.cursor()
    cur.execute("USE ROLE SR_DEV")
    cur.execute("CREATE STAGE IF NOT EXISTS SR_DB.APP.CODE")
    cur.execute(f"PUT 'file://{zpath.as_posix()}' @SR_DB.APP.CODE AUTO_COMPRESS = FALSE OVERWRITE = TRUE")


def load_kb(conn) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import load_kb as kb                                   # reuse the loader's split and MERGE text
    rows = kb.load_rows()
    conn.cursor().execute("USE ROLE SR_DEV")
    run_text(conn, kb.sql_for(rows))
    print(f"   {len(rows)} KB sections")


def run_text(conn, text: str) -> None:
    for cur in conn.execute_stream(io.StringIO(text), remove_comments=True):
        cur.close()


def deploy_apps(conn) -> None:
    cur = conn.cursor()
    cur.execute("USE ROLE SR_ADMIN")
    cur.execute(f"CREATE STAGE IF NOT EXISTS {APP_STAGE[1:]} DIRECTORY = (ENABLE = TRUE)")
    for role in ("SR_UI", "SR_APP"):
        cur.execute(f"GRANT READ ON STAGE {APP_STAGE[1:]} TO ROLE {role}")
    src = ROOT / "streamlit"
    files = [src / "streamlit_app.py", src / "admin_app.py"]
    for pattern in APP_FILES:
        files += sorted(src.glob(pattern))
    for f in files:
        sub = f.parent.relative_to(src).as_posix()
        target = APP_STAGE if sub == "." else f"{APP_STAGE}/{sub}"
        cur.execute(f"PUT 'file://{f.as_posix()}' '{target}' AUTO_COMPRESS = FALSE OVERWRITE = TRUE")
    for name, main, role, title in APPS:
        cur.execute(f"USE ROLE {role}")
        cur.execute(f"CREATE OR REPLACE STREAMLIT {name} FROM '{APP_STAGE}' MAIN_FILE = '{main}' "
                    f"QUERY_WAREHOUSE = SR_WH_XS TITLE = '{title}'")
        cur.execute(f"ALTER STREAMLIT {name} ADD LIVE VERSION FROM LAST")
        print(f"   {name} ({role})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--connection", default="sr")
    ap.add_argument("--from", dest="start", help="resume at this step (file path or step name)")
    ap.add_argument("--skip-apps", action="store_true")
    args = ap.parse_args(argv)
    conn = snowflake.connector.connect(connection_name=args.connection, client_request_mfa_token=True,
                                       client_store_temporary_credential=True)
    conn.cursor().execute("USE WAREHOUSE SR_WH_XS")
    steps, failed, started = plan(), [], args.start is None
    for step, kind in steps:
        started = started or step == args.start
        if not started or (kind == "apps" and args.skip_apps):
            continue
        print(f"== {step}", flush=True)
        try:
            builtin = {"put_sr_lib": put_sr_lib, "load_kb": load_kb, "apps": deploy_apps}.get(kind)
            builtin(conn) if builtin else run_file(conn, step)
            conn.cursor().execute("USE WAREHOUSE SR_WH_XS")
        except Exception as e:                              # noqa: BLE001 - report and decide per kind
            msg = str(e).splitlines()[0][:400]
            if kind == "organizer":
                print(f"   !! failed (organizer step), continuing: {msg}")
                failed.append(step)
                continue
            print(f"   FAILED: {msg}\nDeploy stopped at {step}. Fix it, then rerun with --from {step}")
            return 1
    print("\nDeploy finished.")
    if failed:
        print("Needs organizer action:\n" + "\n".join(f"  - {f}" for f in failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
