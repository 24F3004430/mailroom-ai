import json
import os
import sqlite3
from contextlib import contextmanager
from canonical import canonical_json

DB_PATH = os.getenv("DATABASE_PATH", "mailroom.db")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS evaluations (
            evaluation_id TEXT PRIMARY KEY,
            input_digest TEXT NOT NULL,
            request_json TEXT NOT NULL,
            verifier_json TEXT NOT NULL,
            propose_response TEXT NOT NULL,
            commit_request_json TEXT,
            commit_response TEXT
        );
        CREATE TABLE IF NOT EXISTS dossier_cache (
            fingerprint TEXT PRIMARY KEY,
            proposal_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS proposals (
            evaluation_id TEXT NOT NULL,
            dossier_id TEXT NOT NULL,
            call_id TEXT NOT NULL,
            proposal_json TEXT NOT NULL,
            proposal_digest TEXT NOT NULL,
            PRIMARY KEY (evaluation_id, dossier_id),
            UNIQUE (evaluation_id, call_id),
            FOREIGN KEY (evaluation_id) REFERENCES evaluations(evaluation_id)
        );
        CREATE TABLE IF NOT EXISTS receipts (
            evaluation_id TEXT NOT NULL,
            receipt_id TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            verified INTEGER NOT NULL,
            PRIMARY KEY (evaluation_id, receipt_id),
            FOREIGN KEY (evaluation_id) REFERENCES evaluations(evaluation_id)
        );
        """)


def get_evaluation(evaluation_id):
    with connect() as c:
        row = c.execute("SELECT * FROM evaluations WHERE evaluation_id=?",
                        (evaluation_id,)).fetchone()
        return dict(row) if row else None


def save_evaluation_and_proposals(evaluation_id, digest, request, verifier,
                                  response, proposals):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            c.execute(
                "INSERT INTO evaluations VALUES (?, ?, ?, ?, ?, NULL, NULL)",
                (evaluation_id, digest, canonical_json(request),
                 canonical_json(verifier), canonical_json(response))
            )
            for p in proposals:
                from canonical import proposal_digest
                c.execute(
                    "INSERT INTO proposals VALUES (?, ?, ?, ?, ?)",
                    (evaluation_id, p["dossierId"], p["callId"],
                     canonical_json(p), proposal_digest(p))
                )
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise


def get_cached_proposal(fingerprint):
    with connect() as c:
        row = c.execute("SELECT proposal_json FROM dossier_cache WHERE fingerprint=?",
                        (fingerprint,)).fetchone()
        return json.loads(row["proposal_json"]) if row else None


def save_cached_proposal(fingerprint, proposal):
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO dossier_cache VALUES (?, ?)",
                  (fingerprint, canonical_json(proposal)))


def get_proposals(evaluation_id):
    with connect() as c:
        rows = c.execute("SELECT * FROM proposals WHERE evaluation_id=? ORDER BY rowid",
                         (evaluation_id,)).fetchall()
        return [dict(r) for r in rows]


def save_commit(evaluation_id, commit_request, response, receipts):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            row = c.execute("SELECT commit_request_json, commit_response FROM evaluations WHERE evaluation_id=?",
                            (evaluation_id,)).fetchone()
            if row is None:
                raise KeyError("Unknown evaluation")
            c.execute("UPDATE evaluations SET commit_request_json=?, commit_response=? WHERE evaluation_id=?",
                      (canonical_json(commit_request), canonical_json(response), evaluation_id))
            for receipt, verified in receipts:
                c.execute("INSERT INTO receipts VALUES (?, ?, ?, ?)",
                          (evaluation_id, receipt["receiptId"], canonical_json(receipt), int(verified)))
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
