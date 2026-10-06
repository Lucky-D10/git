"""Per-visit guest identities; lane numbers are never personal identities."""
import uuid


def new_visit():
    return uuid.uuid4().hex


def guest_player(visit_id):
    return "guest-" + visit_id


SCHEMA = """
CREATE TABLE IF NOT EXISTS visits(
 id TEXT PRIMARY KEY, player_id TEXT NOT NULL, started_utc TEXT NOT NULL, closed_utc TEXT);
CREATE TABLE IF NOT EXISTS participant_identity(
 session_id TEXT NOT NULL REFERENCES sessions(id), lane INTEGER NOT NULL,
 participant_id TEXT NOT NULL UNIQUE, visit_id TEXT REFERENCES visits(id),
 identity_kind TEXT NOT NULL, PRIMARY KEY(session_id,lane));
CREATE INDEX IF NOT EXISTS participant_visit ON participant_identity(visit_id,session_id);
"""
