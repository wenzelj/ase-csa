-- csa-work-v2 schema (improvements/docs/PLAN-csa-work-v2.md).
-- Single source of truth for table shapes. Every statement is idempotent:
-- applying this file twice must not error and must not drop or change data.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- core (CRUD)
CREATE TABLE IF NOT EXISTS host (
  name TEXT PRIMARY KEY,
  role TEXT,
  site TEXT,
  os TEXT,
  status TEXT DEFAULT 'active' CHECK (status IN ('active', 'retired')),
  created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS address (
  ip TEXT PRIMARY KEY,
  scope TEXT,
  owner_host TEXT REFERENCES host(name)
);

CREATE TABLE IF NOT EXISTS service (
  id INTEGER PRIMARY KEY,
  host TEXT NOT NULL REFERENCES host(name),
  provider_host TEXT,
  port INTEGER,
  protocol TEXT,
  name TEXT,
  configured INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS service_host ON service(host);
CREATE INDEX IF NOT EXISTS service_provider ON service(provider_host);

CREATE TABLE IF NOT EXISTS flow (
  id INTEGER PRIMARY KEY,
  src_host TEXT NOT NULL REFERENCES host(name),
  dst_host TEXT NOT NULL REFERENCES host(name),
  port INTEGER,
  protocol TEXT,
  purpose TEXT
);
CREATE INDEX IF NOT EXISTS flow_src ON flow(src_host);
CREATE INDEX IF NOT EXISTS flow_dst ON flow(dst_host);

CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  area TEXT,
  question TEXT,
  claim TEXT,
  status TEXT DEFAULT 'UNCONFIRMED' CHECK (status IN ('VERIFIED', 'INFERRED', 'UNCONFIRMED', 'CONFLICTING', 'NOT_FOUND')),
  source_title TEXT,
  page_or_location TEXT,
  excerpt TEXT,
  confidence TEXT,
  gap_or_action TEXT,
  review_state TEXT DEFAULT 'proposed' CHECK (review_state IN ('proposed', 'accepted', 'rejected')),
  created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS evidence_status ON evidence(status);
CREATE INDEX IF NOT EXISTS evidence_review_state ON evidence(review_state);

CREATE TABLE IF NOT EXISTS evidence_source (
  rel_path TEXT PRIMARY KEY,
  sha256 TEXT,
  indexed_at TEXT
);

CREATE TABLE IF NOT EXISTS intake_record (
  id TEXT PRIMARY KEY,
  started_at TEXT,
  finished_at TEXT,
  file_count INTEGER DEFAULT 0,
  row_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS intake_file (
  record_id TEXT NOT NULL REFERENCES intake_record(id),
  rel_path TEXT NOT NULL,
  sha256 TEXT,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processed', 'failed')),
  rows_added INTEGER DEFAULT 0,
  error TEXT,
  PRIMARY KEY (record_id, rel_path)
);

CREATE TABLE IF NOT EXISTS lead (
  id TEXT PRIMARY KEY,
  question TEXT,
  searched_scope TEXT,
  state TEXT DEFAULT 'open' CHECK (state IN ('open', 'resolved', 'not_an_answer', 'retired')),
  evidence_ids TEXT
);
CREATE INDEX IF NOT EXISTS lead_state ON lead(state);

CREATE TABLE IF NOT EXISTS gap_check (
  id TEXT PRIMARY KEY,
  ts TEXT,
  dr_id TEXT,
  text TEXT,
  leads_found INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS review_event (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  actor TEXT,
  action TEXT,
  subject_type TEXT,
  subject_id TEXT,
  note TEXT,
  before_hash TEXT,
  after_hash TEXT
);
CREATE INDEX IF NOT EXISTS review_event_subject ON review_event(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS review_event_ts ON review_event(ts);

-- ------------------------------------------------------------- derived tables
CREATE TABLE IF NOT EXISTS graph_node (
  node_id TEXT PRIMARY KEY,
  label TEXT,
  kind TEXT,
  evidence_ids TEXT
);

CREATE TABLE IF NOT EXISTS graph_edge (
  edge_id TEXT PRIMARY KEY,
  src TEXT,
  dst TEXT,
  kind TEXT,
  evidence_ids TEXT
);
CREATE INDEX IF NOT EXISTS graph_edge_src ON graph_edge(src);
CREATE INDEX IF NOT EXISTS graph_edge_dst ON graph_edge(dst);

CREATE TABLE IF NOT EXISTS alias (
  alias TEXT NOT NULL,
  subject_type TEXT,
  subject_id TEXT,
  scope TEXT,
  PRIMARY KEY (alias, subject_type, subject_id, scope)
);

CREATE TABLE IF NOT EXISTS entity (
  kind TEXT,
  norm TEXT,
  file_ref TEXT,
  PRIMARY KEY (kind, norm, file_ref)
);

-- ------------------------------------- read-only mirror of the discovery index
CREATE TABLE IF NOT EXISTS indexed_file (
  rel_path TEXT PRIMARY KEY,
  sha256 TEXT,
  size INTEGER,
  indexed_at TEXT
);

CREATE TABLE IF NOT EXISTS indexed_chunk (
  id INTEGER PRIMARY KEY,
  rel_path TEXT REFERENCES indexed_file(rel_path),
  heading TEXT,
  text TEXT
);
CREATE INDEX IF NOT EXISTS indexed_chunk_rel ON indexed_chunk(rel_path);

-- ------------------------------------- application scope metadata
CREATE TABLE IF NOT EXISTS application_scope (
    application_key TEXT NOT NULL,
    host_name TEXT NOT NULL REFERENCES host(name),
    membership TEXT CHECK (membership IN ('owned', 'peer')) NOT NULL,
    basis TEXT,
    evidence_ids TEXT,
    source_ref TEXT,
    review_state TEXT DEFAULT 'proposed' CHECK (review_state IN ('proposed', 'accepted', 'rejected')),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    PRIMARY KEY (application_key, host_name)
);
CREATE INDEX IF NOT EXISTS application_scope_app ON application_scope(application_key);
CREATE INDEX IF NOT EXISTS application_scope_membership ON application_scope(membership);

