import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix=""):
    return prefix + uuid4().hex[:16]


def data_dir():
    path = Path(os.environ.get("ZANDOP_DATA_DIR", "data")).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connect():
    connection = sqlite3.connect(data_dir() / "zandop.sqlite3", timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize():
    with connect() as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS leads (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL,
          website TEXT NOT NULL DEFAULT '', service TEXT NOT NULL,
          platform TEXT NOT NULL DEFAULT '', industry TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL, score INTEGER NOT NULL DEFAULT 0,
          stage INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'ready',
          demo INTEGER NOT NULL DEFAULT 0, details TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(email, demo)
        );
        CREATE TABLE IF NOT EXISTS events (
          id TEXT PRIMARY KEY, lead_id TEXT REFERENCES leads(id), agent TEXT NOT NULL,
          action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
          id TEXT PRIMARY KEY, lead_id TEXT NOT NULL REFERENCES leads(id),
          kind TEXT NOT NULL, title TEXT NOT NULL, payload TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
          decided_at TEXT, decided_by TEXT, result TEXT
        );
        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY, lead_id TEXT NOT NULL REFERENCES leads(id),
          kind TEXT NOT NULL, version INTEGER NOT NULL, title TEXT NOT NULL,
          path TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(lead_id,kind,version)
        );
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY, lead_id TEXT NOT NULL REFERENCES leads(id),
          direction TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
          status TEXT NOT NULL, provider_id TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS webhooks (
          id TEXT PRIMARY KEY, provider TEXT NOT NULL, received_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS outbox (
          id TEXT PRIMARY KEY, lead_id TEXT NOT NULL REFERENCES leads(id),
          kind TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0, result TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS suppressions (email TEXT PRIMARY KEY, reason TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS referral_clicks (
          id TEXT PRIMARY KEY, lead_id TEXT NOT NULL REFERENCES leads(id), created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS document_policy (
          document_id TEXT PRIMARY KEY REFERENCES documents(id), sha256 TEXT NOT NULL,
          requires_approval INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS outreach_attempts (
          id TEXT PRIMARY KEY, action_id TEXT NOT NULL, lead_id TEXT NOT NULL REFERENCES leads(id),
          email TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS project_starts (
          lead_id TEXT PRIMARY KEY REFERENCES leads(id), week_key TEXT NOT NULL,
          quote_reference TEXT NOT NULL, amount INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        """)
        # Retain old approvals when a client-specific quote is revised.
        schema = db.execute("SELECT sql FROM sqlite_master WHERE name='approvals'").fetchone()[0]
        if "UNIQUE(lead_id, kind)" in schema:
            db.executescript("""
            CREATE TABLE approvals_v2 AS SELECT * FROM approvals;
            DROP TABLE approvals;
            CREATE TABLE approvals (
              id TEXT PRIMARY KEY, lead_id TEXT NOT NULL REFERENCES leads(id), kind TEXT NOT NULL,
              title TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
              created_at TEXT NOT NULL, decided_at TEXT, decided_by TEXT, result TEXT
            );
            INSERT INTO approvals SELECT * FROM approvals_v2;
            DROP TABLE approvals_v2;
            """)
        db.execute("CREATE INDEX IF NOT EXISTS approvals_latest ON approvals(lead_id,kind,created_at)")


def unpack(row):
    if row is None:
        return None
    result = dict(row)
    for key in ("details", "payload"):
        if key in result:
            result[key] = json.loads(result[key])
    return result


def event(db, lead_id, agent, action, detail):
    db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",
               (uid("ev_"), lead_id, agent, action, str(detail), now()))


def setting(db, key, default=None):
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_setting(db, key, value):
    db.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, json.dumps(value)))


def save_lead(db, lead):
    lead["updated_at"] = now()
    db.execute("UPDATE leads SET score=?,stage=?,status=?,details=?,updated_at=? WHERE id=?",
               (lead["score"], lead["stage"], lead["status"], json.dumps(lead["details"]), lead["updated_at"], lead["id"]))


def add_lead(db, data, demo=False):
    lead_id = uid("ld_")
    db.execute("INSERT INTO leads(id,name,email,website,service,platform,industry,source,demo,details,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (lead_id, data["name"], data["email"].strip().lower(), data.get("website", ""), data["service"],
                data.get("platform", ""), data.get("industry", ""), data.get("source", "manual"), int(demo),
                json.dumps(data.get("details", {})), now(), now()))
    event(db, lead_id, "CRM", "lead.created", "Demo lead imported" if demo else "Lead imported")
    return unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
