from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import data_dir


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return uuid.uuid4().hex


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS mobile_devices (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL,
  token_hash TEXT UNIQUE, ticket_hash TEXT UNIQUE, created_at TEXT NOT NULL,
  last_seen TEXT NOT NULL, expires_at TEXT NOT NULL, address TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mobile_chats (
  id TEXT PRIMARY KEY, device_id TEXT NOT NULL REFERENCES mobile_devices(id) ON DELETE CASCADE,
  request_key TEXT NOT NULL, request_hash TEXT NOT NULL,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  status TEXT NOT NULL, content TEXT NOT NULL, state_json TEXT NOT NULL,
  error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, revision INTEGER NOT NULL,
  UNIQUE(device_id, request_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS mobile_active_conversation ON mobile_chats(conversation_id)
  WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_approvals (
 id TEXT PRIMARY KEY, project_id TEXT, conversation_id TEXT, job_id TEXT,
 tool TEXT NOT NULL, signature TEXT NOT NULL, details_json TEXT NOT NULL,
 status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL, resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_approval_scope ON agent_approvals(project_id,conversation_id,status);
CREATE TABLE IF NOT EXISTS source_categories (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  name TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(project_id, name)
);
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  name TEXT NOT NULL, kind TEXT NOT NULL, original_path TEXT NOT NULL,
  segments_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'pending',
  error TEXT, created_at TEXT NOT NULL,
  category_id TEXT REFERENCES source_categories(id) ON DELETE SET NULL,
  origin_url TEXT
);
CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  source_ids_json TEXT NOT NULL, kind TEXT NOT NULL, format TEXT NOT NULL,
  path TEXT NOT NULL, title TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_scopes (
  source_id TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
  original_source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
  mode TEXT NOT NULL, selection_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  kind TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL DEFAULT '{}', result_json TEXT NOT NULL DEFAULT '{}',
  error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_retries (
  family TEXT NOT NULL, job_id TEXT NOT NULL, enabled INTEGER NOT NULL,
  limit_count INTEGER NOT NULL, retry_count INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'running', next_at TEXT, last_error TEXT,
  reason TEXT, updated_at TEXT NOT NULL, PRIMARY KEY (family,job_id)
);
CREATE TABLE IF NOT EXISTS task_manual_retries (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL, payload_sha256 TEXT NOT NULL, previous_error_sha256 TEXT NOT NULL,
 previous_reason TEXT, previous_retry_count INTEGER NOT NULL, previous_progress INTEGER NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(job_id,request_id)
);
CREATE TRIGGER IF NOT EXISTS jobs_retry_cleanup AFTER DELETE ON jobs BEGIN
  DELETE FROM task_retries WHERE family='project' AND job_id=OLD.id;
END;
CREATE TABLE IF NOT EXISTS source_vision_cache (
 cache_key TEXT PRIMARY KEY, description TEXT NOT NULL, characters INTEGER NOT NULL,
 accessed_at TEXT NOT NULL, project_id TEXT REFERENCES projects(id) ON DELETE CASCADE, source_id TEXT
);
CREATE TABLE IF NOT EXISTS exercise_sets (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  source_ids_json TEXT NOT NULL, title TEXT NOT NULL, questions_json TEXT NOT NULL,
  solutions_json TEXT NOT NULL, difficulty INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'assigned', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
  id TEXT PRIMARY KEY, exercise_set_id TEXT NOT NULL REFERENCES exercise_sets(id),
  answers_json TEXT NOT NULL, grade_json TEXT NOT NULL, score REAL NOT NULL,
  feynman_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS homework_attempts (
  id TEXT PRIMARY KEY, exercise_set_id TEXT NOT NULL REFERENCES exercise_sets(id),
  project_id TEXT NOT NULL REFERENCES projects(id), conversation_id TEXT,
  job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id), source_version TEXT NOT NULL,
  answers_json TEXT NOT NULL, options_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'accepted', grade_json TEXT NOT NULL DEFAULT '{}',
  analysis_json TEXT NOT NULL DEFAULT '{}', causes_json TEXT NOT NULL DEFAULT '[]',
  solution_artifact_id TEXT, feedback_artifact_id TEXT, prompt_message_id TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS homework_by_project ON homework_attempts(project_id,created_at);
CREATE TABLE IF NOT EXISTS mastery (
  topic TEXT PRIMARY KEY, score REAL NOT NULL, evidence_count INTEGER NOT NULL,
  quiz_score REAL, feynman_score REAL, self_rating REAL, updated_at TEXT NOT NULL,
  difficulty_rating REAL
);
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  provider TEXT NOT NULL, remote_thread_id TEXT, created_at TEXT NOT NULL,
  source_ids_json TEXT NOT NULL DEFAULT '[]', model TEXT, reasoning_effort TEXT
);
CREATE TABLE IF NOT EXISTS message_focus_references (
 message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
 conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 target_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
 reference_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS message_focus_by_conversation ON message_focus_references(conversation_id);
CREATE TABLE IF NOT EXISTS mentor_handoffs (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  conversation_id TEXT REFERENCES conversations(id), job_id TEXT NOT NULL REFERENCES jobs(id),
  provider TEXT NOT NULL, model TEXT, reasoning_effort TEXT,
  packet_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_learning_modes (
  conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
  learning_mode TEXT NOT NULL CHECK(learning_mode IN ('overview','deep','research')),
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS generation_steps (
  job_id TEXT NOT NULL REFERENCES jobs(id), step_key TEXT NOT NULL,
  response TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(job_id,step_key)
);
CREATE TABLE IF NOT EXISTS document_snapshots (
  job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(id), title TEXT NOT NULL,
  content TEXT NOT NULL, content_sha256 TEXT NOT NULL,
  source_ids_json TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS document_snapshots_project ON document_snapshots(project_id);
CREATE UNIQUE INDEX IF NOT EXISTS document_export_request ON jobs(project_id,json_extract(payload_json,'$.export_request_id'))
  WHERE kind='export' AND json_extract(payload_json,'$.export_request_id') IS NOT NULL;
CREATE TABLE IF NOT EXISTS job_file_outputs (
  job_id TEXT NOT NULL REFERENCES jobs(id), path TEXT NOT NULL,
  PRIMARY KEY(job_id,path)
);
CREATE TABLE IF NOT EXISTS execution_spans (
 id TEXT NOT NULL, segment INTEGER NOT NULL DEFAULT 0, job_id TEXT,
 project_id TEXT, conversation_id TEXT, resource TEXT NOT NULL, provider TEXT,
 label TEXT NOT NULL DEFAULT '', priority INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL, queued_at TEXT NOT NULL, started_at TEXT, ended_at TEXT,
 duration_ms INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (id,segment)
);
CREATE INDEX IF NOT EXISTS execution_spans_job ON execution_spans(job_id,queued_at);
CREATE TABLE IF NOT EXISTS agent_tool_events (
  id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), conversation_id TEXT REFERENCES conversations(id),
  job_id TEXT REFERENCES jobs(id), tool TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_assets (
  id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), path TEXT NOT NULL,
  mime TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_asset_scopes (
  asset_id TEXT PRIMARY KEY REFERENCES agent_assets(id) ON DELETE CASCADE,
  scope_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_workspaces (
  scope_key TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  path TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS codex_agent_threads (
  thread_id TEXT PRIMARY KEY, tool_signature TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_dialogue_state (
  conversation_id TEXT PRIMARY KEY REFERENCES conversations(id), published_count INTEGER NOT NULL,
  messages_json TEXT NOT NULL, updated_at TEXT NOT NULL, protocol_version INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS agent_dialogue_scopes (
  conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(id), scope_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS generation_dialogue_outputs (
  job_id TEXT PRIMARY KEY REFERENCES jobs(id), conversation_id TEXT NOT NULL REFERENCES conversations(id),
  message_id TEXT NOT NULL REFERENCES messages(id)
);
CREATE TABLE IF NOT EXISTS lesson_questionnaires (
  id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id),
  project_id TEXT NOT NULL REFERENCES projects(id), conversation_id TEXT NOT NULL REFERENCES conversations(id),
  artifact_id TEXT REFERENCES artifacts(id) ON DELETE SET NULL, title TEXT NOT NULL,
  source_ids_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  difficulties_json TEXT NOT NULL DEFAULT '[]', other_text TEXT NOT NULL DEFAULT '',
  focus_json TEXT NOT NULL DEFAULT '{}',
  reply_status TEXT NOT NULL DEFAULT 'pending', user_message_id TEXT REFERENCES messages(id),
  reply_message_id TEXT REFERENCES messages(id), error TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_questionnaires_project ON lesson_questionnaires(project_id,created_at);
-- Separate, repeatable content doubts retain the original questionnaire and
-- its optional assessment links. Creating a draft does not create an AI job.
CREATE TABLE IF NOT EXISTS lesson_content_checks (
  id TEXT PRIMARY KEY, parent_questionnaire_id TEXT NOT NULL REFERENCES lesson_questionnaires(id) ON DELETE CASCADE,
  job_id TEXT NOT NULL REFERENCES jobs(id), project_id TEXT NOT NULL REFERENCES projects(id),
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  artifact_id TEXT REFERENCES artifacts(id) ON DELETE SET NULL, title TEXT NOT NULL,
  source_ids_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  difficulties_json TEXT NOT NULL DEFAULT '["content_accuracy"]', other_text TEXT NOT NULL DEFAULT '',
  focus_json TEXT NOT NULL DEFAULT '{}', reply_status TEXT NOT NULL DEFAULT 'pending',
  user_message_id TEXT REFERENCES messages(id), reply_message_id TEXT REFERENCES messages(id), error TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_content_checks_project ON lesson_content_checks(project_id,created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_content_checks_pending ON lesson_content_checks(job_id) WHERE status='pending';
CREATE TABLE IF NOT EXISTS reading_sessions (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  source_ids_json TEXT NOT NULL, fingerprint TEXT NOT NULL,
  provider TEXT NOT NULL, model TEXT, reasoning_effort TEXT,
  notes_json TEXT NOT NULL, source_reading_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_readings_project ON reading_sessions(project_id);
CREATE TABLE IF NOT EXISTS knowledge_maps (
  id TEXT PRIMARY KEY, reading_id TEXT NOT NULL REFERENCES reading_sessions(id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(id), schema_version INTEGER NOT NULL,
  provider TEXT NOT NULL, model TEXT, reasoning_effort TEXT, fingerprint TEXT NOT NULL,
  structure_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_reading ON knowledge_maps(reading_id,created_at);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
  role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_history_versions (
  conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS history_message_insert AFTER INSERT ON messages BEGIN
  INSERT INTO conversation_history_versions VALUES (NEW.conversation_id,1)
  ON CONFLICT(conversation_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER IF NOT EXISTS history_message_delete AFTER DELETE ON messages BEGIN
  INSERT INTO conversation_history_versions VALUES (OLD.conversation_id,1)
  ON CONFLICT(conversation_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER IF NOT EXISTS history_message_update AFTER UPDATE ON messages
WHEN OLD.id IS NOT NEW.id OR OLD.conversation_id IS NOT NEW.conversation_id
  OR OLD.content IS NOT NEW.content OR OLD.role IS NOT NEW.role OR OLD.created_at IS NOT NEW.created_at
BEGIN
  INSERT INTO conversation_history_versions VALUES (OLD.conversation_id,1)
  ON CONFLICT(conversation_id) DO UPDATE SET revision=revision+1;
  INSERT INTO conversation_history_versions SELECT NEW.conversation_id,1
  WHERE NEW.conversation_id IS NOT OLD.conversation_id
  ON CONFLICT(conversation_id) DO UPDATE SET revision=revision+1;
END;
CREATE TABLE IF NOT EXISTS deleted_conversations (
  conversation_id TEXT PRIMARY KEY REFERENCES conversations(id), deleted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deleted_job_records (
  job_id TEXT PRIMARY KEY REFERENCES jobs(id), deleted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_workspaces (
  conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
  title TEXT NOT NULL, title_manual INTEGER NOT NULL DEFAULT 0,
  draft TEXT NOT NULL DEFAULT '', reading_id TEXT, model_choice TEXT,
  updated_at TEXT NOT NULL, opened_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_workspaces (
  project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_teaching_styles (
  conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
  explanation_style TEXT NOT NULL CHECK(explanation_style IN ('clear','balanced','academic')),
  output_language TEXT NOT NULL DEFAULT 'zh' CHECK(output_language IN ('zh','bilingual','en')),
  review_mode TEXT NOT NULL DEFAULT 'express' CHECK(review_mode IN ('express','fast','balanced','strict')),
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_state (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS desktop_notices (
  id INTEGER PRIMARY KEY AUTOINCREMENT, notice_key TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
  target_json TEXT NOT NULL, created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS desktop_notices_pending ON desktop_notices(status,id);
CREATE INDEX IF NOT EXISTS desktop_artifacts_created ON artifacts(created_at);
CREATE INDEX IF NOT EXISTS desktop_jobs_updated ON jobs(updated_at);
CREATE TABLE IF NOT EXISTS project_navigation (
  project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  pinned INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS conversation_navigation (
  conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
  pinned INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS removed_projects (
  project_id TEXT PRIMARY KEY REFERENCES projects(id), removed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifact_sources (
  artifact_id TEXT PRIMARY KEY REFERENCES artifacts(id) ON DELETE CASCADE,
  source_id TEXT NOT NULL UNIQUE REFERENCES sources(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_id);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id,created_at);
CREATE INDEX IF NOT EXISTS idx_sources_project ON sources(project_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id);
CREATE TABLE IF NOT EXISTS learning_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT NOT NULL UNIQUE,
  project_id TEXT, conversation_id TEXT, kind TEXT NOT NULL,
  provider TEXT, model TEXT, effort TEXT, payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_learning_pending ON learning_events(status,id);
CREATE TABLE IF NOT EXISTS learning_insights (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL REFERENCES learning_events(id),
  topic TEXT NOT NULL, kind TEXT NOT NULL, dimension TEXT NOT NULL DEFAULT '',
  observation TEXT NOT NULL, quote TEXT NOT NULL, confidence TEXT NOT NULL,
  created_at TEXT NOT NULL, anchors_json TEXT NOT NULL DEFAULT '[]', UNIQUE(event_id,topic,kind,dimension)
);
CREATE TABLE IF NOT EXISTS learning_runs (
  id TEXT PRIMARY KEY, event_ids_json TEXT NOT NULL, provider TEXT NOT NULL,
  model TEXT, status TEXT NOT NULL, input_chars INTEGER NOT NULL,
  error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_insight_controls (
  insight_id INTEGER PRIMARY KEY REFERENCES learning_insights(id),
  correction TEXT, deleted INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_event_profile_blocks (
  event_id INTEGER PRIMARY KEY REFERENCES learning_events(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_event_filters (
  event_id INTEGER PRIMARY KEY REFERENCES learning_events(id),
  eligible INTEGER NOT NULL, policy_version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS learning_insight_evidence_filters (
  insight_id INTEGER PRIMARY KEY REFERENCES learning_insights(id) ON DELETE CASCADE,
  eligible INTEGER NOT NULL, policy_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS legacy_profile_exclusions (
  topic TEXT PRIMARY KEY, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS practice_options (
  exercise_set_id TEXT PRIMARY KEY REFERENCES exercise_sets(id),
  recovery_mode TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS practice_hints (
  exercise_set_id TEXT NOT NULL REFERENCES exercise_sets(id), question_index INTEGER NOT NULL,
  kind TEXT NOT NULL, level INTEGER NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(exercise_set_id,question_index,kind,level)
);
CREATE TABLE IF NOT EXISTS practice_submission_locks (
  exercise_set_id TEXT PRIMARY KEY REFERENCES exercise_sets(id), token TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_items (
  id TEXT PRIMARY KEY, origin_set_id TEXT NOT NULL REFERENCES exercise_sets(id), question_index INTEGER NOT NULL,
  interval_days INTEGER NOT NULL, baseline_at TEXT NOT NULL, due_at TEXT NOT NULL,
  active_set_id TEXT REFERENCES exercise_sets(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(origin_set_id,question_index)
);
CREATE TABLE IF NOT EXISTS review_sessions (
  exercise_set_id TEXT PRIMARY KEY REFERENCES exercise_sets(id), items_json TEXT NOT NULL,
  started_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE IF NOT EXISTS review_item_versions (
  review_item_id TEXT PRIMARY KEY REFERENCES review_items(id) ON DELETE CASCADE,
  snapshot_json TEXT NOT NULL, fingerprint TEXT NOT NULL, verified INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS practice_repair_links (
  parent_set_id TEXT PRIMARY KEY REFERENCES exercise_sets(id),
  new_set_id TEXT NOT NULL REFERENCES exercise_sets(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS practice_progression_links (
  parent_set_id TEXT PRIMARY KEY REFERENCES exercise_sets(id),
  new_set_id TEXT NOT NULL REFERENCES exercise_sets(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS practice_repair_contexts (
  new_set_id TEXT PRIMARY KEY REFERENCES exercise_sets(id) ON DELETE CASCADE,
  parent_set_id TEXT NOT NULL REFERENCES exercise_sets(id) ON DELETE CASCADE,
  submission_id TEXT NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
  context_signature TEXT NOT NULL, spec_json TEXT NOT NULL, public_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_practice_repair_context_scope
  ON practice_repair_contexts(parent_set_id,submission_id,context_signature);
CREATE TABLE IF NOT EXISTS learning_goals (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL, domain TEXT NOT NULL, intent TEXT NOT NULL,
  criterion TEXT NOT NULL DEFAULT '', source_ids_json TEXT NOT NULL DEFAULT '[]',
  origin_json TEXT NOT NULL DEFAULT '{}', paused INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_learning_goals_project ON learning_goals(project_id,created_at);
CREATE TABLE IF NOT EXISTS learning_goal_prerequisites (
  goal_id TEXT NOT NULL REFERENCES learning_goals(id) ON DELETE CASCADE,
  prerequisite_id TEXT NOT NULL REFERENCES learning_goals(id) ON DELETE CASCADE,
  reason TEXT NOT NULL, basis TEXT NOT NULL DEFAULT 'manual',
  PRIMARY KEY(goal_id,prerequisite_id), CHECK(goal_id!=prerequisite_id)
);
CREATE TABLE IF NOT EXISTS conversation_learning_goals (
  conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
  goal_id TEXT REFERENCES learning_goals(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS learning_goal_checks (
  exercise_set_id TEXT PRIMARY KEY REFERENCES exercise_sets(id) ON DELETE CASCADE,
  goal_id TEXT NOT NULL REFERENCES learning_goals(id) ON DELETE CASCADE,
  dimensions_json TEXT NOT NULL, goal_snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lesson_understanding_checks (
  job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  questionnaire_id TEXT NOT NULL REFERENCES lesson_questionnaires(id) ON DELETE CASCADE,
  context_signature TEXT NOT NULL,
  exercise_set_id TEXT REFERENCES exercise_sets(id) ON DELETE SET NULL,
  public_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lesson_checks_context ON lesson_understanding_checks(questionnaire_id,context_signature);
-- Books belong to the application, independently of project/chat lifetimes.
CREATE TABLE IF NOT EXISTS library_books (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL,
  original_path TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE, page_count INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'stored', toc_pages TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS library_nodes (
  id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES library_books(id) ON DELETE CASCADE,
  parent_id TEXT REFERENCES library_nodes(id) ON DELETE CASCADE,
  position INTEGER NOT NULL, title TEXT NOT NULL, kind TEXT NOT NULL,
  printed_page INTEGER, start_page INTEGER, end_page INTEGER,
  start_y REAL NOT NULL DEFAULT 0, end_y REAL NOT NULL DEFAULT 1,
  confirmed INTEGER NOT NULL DEFAULT 0, provenance_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_library_nodes_book ON library_nodes(book_id,position);
CREATE TABLE IF NOT EXISTS library_readings (
  id TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES library_nodes(id) ON DELETE CASCADE,
  signature TEXT NOT NULL UNIQUE, provider TEXT NOT NULL, model TEXT, effort TEXT,
  status TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', warnings_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  depth TEXT NOT NULL DEFAULT 'index', focus TEXT NOT NULL DEFAULT '', vision_model TEXT
);
CREATE INDEX IF NOT EXISTS idx_library_readings_node_status ON library_readings(node_id,status,updated_at DESC);
CREATE TABLE IF NOT EXISTS library_page_observations (
  book_id TEXT NOT NULL REFERENCES library_books(id) ON DELETE CASCADE,
  cache_key TEXT NOT NULL, visual_text TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(book_id,cache_key)
);
CREATE TABLE IF NOT EXISTS library_chunks (
  reading_id TEXT NOT NULL REFERENCES library_readings(id) ON DELETE CASCADE,
  page INTEGER NOT NULL, locator TEXT NOT NULL, original_text TEXT NOT NULL,
  visual_text TEXT NOT NULL DEFAULT '', image_path TEXT, image_sha256 TEXT,
  PRIMARY KEY(reading_id,page)
);
CREATE TABLE IF NOT EXISTS library_reading_annotations (
  reading_id TEXT PRIMARY KEY REFERENCES library_readings(id) ON DELETE CASCADE,
  suspect INTEGER NOT NULL CHECK(suspect IN (0,1)), comment TEXT NOT NULL,
  revision INTEGER NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS library_jobs (
  id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES library_books(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}', error TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS library_jobs_retry_cleanup AFTER DELETE ON library_jobs BEGIN
  DELETE FROM task_retries WHERE family='library' AND job_id=OLD.id;
END;
CREATE TABLE IF NOT EXISTS library_steps (
  job_id TEXT NOT NULL REFERENCES library_jobs(id) ON DELETE CASCADE,
  step_key TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(job_id,step_key)
);
-- Request accounting survives deletion of the corresponding book/job.
CREATE TABLE IF NOT EXISTS library_model_usage (
  id TEXT PRIMARY KEY, day TEXT NOT NULL,
  job_id TEXT REFERENCES library_jobs(id) ON DELETE SET NULL,
  provider TEXT NOT NULL, model TEXT, reserved_tokens INTEGER NOT NULL,
  charged_tokens INTEGER NOT NULL DEFAULT 0, reported_tokens INTEGER,
  status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_library_model_usage_day ON library_model_usage(day,status);
CREATE TABLE IF NOT EXISTS conversation_library (
  conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
  mode TEXT NOT NULL DEFAULT 'auto', references_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS conversation_library_history (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  query TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_library_history_chat ON conversation_library_history(conversation_id,created_at);
CREATE TABLE IF NOT EXISTS library_semantic_pages (
  reading_id TEXT NOT NULL REFERENCES library_readings(id) ON DELETE CASCADE,
  page INTEGER NOT NULL, model_key TEXT NOT NULL, text_hash TEXT NOT NULL,
  next_ordinal INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
  PRIMARY KEY(reading_id,page,model_key)
);
CREATE TABLE IF NOT EXISTS library_embeddings (
  reading_id TEXT NOT NULL REFERENCES library_readings(id) ON DELETE CASCADE,
  model_key TEXT NOT NULL, page INTEGER NOT NULL, ordinal INTEGER NOT NULL,
  kind TEXT NOT NULL, start_char INTEGER NOT NULL, end_char INTEGER NOT NULL,
  text_hash TEXT NOT NULL, dims INTEGER NOT NULL, vector BLOB NOT NULL,
  PRIMARY KEY(reading_id,model_key,page,ordinal)
);
CREATE TRIGGER IF NOT EXISTS library_semantic_insert AFTER INSERT ON library_chunks BEGIN
  DELETE FROM library_semantic_pages WHERE reading_id=NEW.reading_id AND page=NEW.page;
  DELETE FROM library_embeddings WHERE reading_id=NEW.reading_id AND page=NEW.page;
END;
CREATE TRIGGER IF NOT EXISTS library_semantic_update AFTER UPDATE OF original_text,visual_text ON library_chunks BEGIN
  DELETE FROM library_semantic_pages WHERE reading_id=NEW.reading_id AND page=NEW.page;
  DELETE FROM library_embeddings WHERE reading_id=NEW.reading_id AND page=NEW.page;
END;
CREATE TRIGGER IF NOT EXISTS library_semantic_delete AFTER DELETE ON library_chunks BEGIN
  DELETE FROM library_semantic_pages WHERE reading_id=OLD.reading_id AND page=OLD.page;
  DELETE FROM library_embeddings WHERE reading_id=OLD.reading_id AND page=OLD.page;
END;
"""

_schema_lock = threading.Lock()
_initialized_databases: dict[Path, tuple[int, int]] = {}


def _initialize(conn: sqlite3.Connection, path: Path) -> None:
    # Initialize once per database, before serving concurrent UI/MCP requests.
    # Re-running journal/schema PRAGMAs on every read can fail immediately with
    # SQLITE_BUSY when another request is creating a project.
    with _schema_lock:
        stat = path.stat()
        identity = (stat.st_dev, stat.st_ino)
        if _initialized_databases.get(path) == identity:
            return
        if conn.execute("PRAGMA journal_mode").fetchone()[0] != 'wal':
            conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
        if 'project_id' not in {row[1] for row in conn.execute('PRAGMA table_info(source_vision_cache)')}:
            conn.execute('ALTER TABLE source_vision_cache ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE CASCADE')
        if 'source_id' not in {row[1] for row in conn.execute('PRAGMA table_info(source_vision_cache)')}:
            conn.execute('ALTER TABLE source_vision_cache ADD COLUMN source_id TEXT')
        conn.execute('CREATE INDEX IF NOT EXISTS vision_cache_source ON source_vision_cache(source_id)')
        # Exact source ownership for new records. Legacy rows without ownership
        # are conservatively cleared in this project (and unknown old scope).
        conn.execute('CREATE TRIGGER IF NOT EXISTS source_vision_cleanup AFTER DELETE ON sources BEGIN '
            'DELETE FROM source_vision_cache WHERE source_id=OLD.id OR '
            '(source_id IS NULL AND (project_id=OLD.project_id OR project_id IS NULL)); END;')
        reading_columns = {row[1] for row in conn.execute('PRAGMA table_info(library_readings)')}
        for name, default in (('depth', 'index'), ('focus', '')):
            if name not in reading_columns:
                conn.execute(f"ALTER TABLE library_readings ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
        if 'vision_model' not in reading_columns:
            conn.execute('ALTER TABLE library_readings ADD COLUMN vision_model TEXT')
        if "difficulty_rating" not in {row[1] for row in conn.execute("PRAGMA table_info(mastery)")}:
            conn.execute("ALTER TABLE mastery ADD COLUMN difficulty_rating REAL")
        if "category_id" not in {row[1] for row in conn.execute("PRAGMA table_info(sources)")}:
            conn.execute("ALTER TABLE sources ADD COLUMN category_id TEXT REFERENCES source_categories(id) ON DELETE SET NULL")
        if "origin_url" not in {row[1] for row in conn.execute("PRAGMA table_info(sources)")}:
            conn.execute("ALTER TABLE sources ADD COLUMN origin_url TEXT")
            # Preserve the origin of older URL imports even after their kind
            # became .html/.pdf/.sfvideo or a failed download was cleaned up.
            conn.execute("UPDATE sources SET origin_url=original_path WHERE kind IN ('url','video_url') "
                         "AND (original_path LIKE 'https://%' OR original_path LIKE 'http://%')")
            conn.execute("UPDATE sources SET origin_url=(SELECT json_extract(j.payload_json,'$.url') FROM jobs j "
                         "WHERE j.project_id=sources.project_id AND json_valid(j.payload_json) "
                         "AND json_extract(j.payload_json,'$.source_id')=sources.id "
                         "AND (json_extract(j.payload_json,'$.url') LIKE 'https://%' OR json_extract(j.payload_json,'$.url') LIKE 'http://%') "
                         "ORDER BY j.created_at DESC LIMIT 1) WHERE origin_url IS NULL")
        if "source_ids_json" not in {row[1] for row in conn.execute("PRAGMA table_info(conversations)")}:
            conn.execute("ALTER TABLE conversations ADD COLUMN source_ids_json TEXT NOT NULL DEFAULT '[]'")
        conversation_columns = {row[1] for row in conn.execute('PRAGMA table_info(conversations)')}
        for name in ('model', 'reasoning_effort'):
            if name not in conversation_columns:
                conn.execute(f'ALTER TABLE conversations ADD COLUMN {name} TEXT')
        if 'anchors_json' not in {row[1] for row in conn.execute('PRAGMA table_info(learning_insights)')}:
            conn.execute("ALTER TABLE learning_insights ADD COLUMN anchors_json TEXT NOT NULL DEFAULT '[]'")
        if 'focus_json' not in {row[1] for row in conn.execute('PRAGMA table_info(lesson_questionnaires)')}:
            conn.execute("ALTER TABLE lesson_questionnaires ADD COLUMN focus_json TEXT NOT NULL DEFAULT '{}'")
        if 'protocol_version' not in {row[1] for row in conn.execute('PRAGMA table_info(agent_dialogue_state)')}:
            # Legacy tool histories may contain private assessment solutions.
            # Keep visible chat intact, but never restore unversioned state.
            conn.execute('ALTER TABLE agent_dialogue_state ADD COLUMN protocol_version INTEGER NOT NULL DEFAULT 0')
        if 'model_choice' not in {row[1] for row in conn.execute('PRAGMA table_info(conversation_workspaces)')}:
            conn.execute('ALTER TABLE conversation_workspaces ADD COLUMN model_choice TEXT')
        teaching_columns = {row[1] for row in conn.execute('PRAGMA table_info(conversation_teaching_styles)')}
        if 'output_language' not in teaching_columns:
            conn.execute("ALTER TABLE conversation_teaching_styles ADD COLUMN output_language TEXT NOT NULL DEFAULT 'zh'")
        if 'review_mode' not in teaching_columns:
            conn.execute("ALTER TABLE conversation_teaching_styles ADD COLUMN review_mode TEXT NOT NULL DEFAULT 'express'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_category ON sources(category_id)")
        # The first installation of desktop notices starts here. Historic
        # completed work must not produce a burst of notifications on upgrade.
        conn.execute("INSERT OR IGNORE INTO workspace_state VALUES ('desktop_notices_since',?)", (now(),))
        conn.commit()
        _initialized_databases[path] = identity


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = data_dir() / "studyforge.sqlite3"
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        _initialize(conn, path)
        yield conn
        conn.commit()
    finally:
        conn.close()


def one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(sql, params).fetchone()
        return dict(row) if row else None


def many(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connect() as db:
        return [dict(row) for row in db.execute(sql, params).fetchall()]


def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
    with connect() as db:
        db.execute(sql, params)


def j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def unj(value: str | None, default: Any = None) -> Any:
    return json.loads(value) if value else default


def create_project(name: str) -> dict[str, Any]:
    project = {"id": uid(), "name": name.strip() or "未命名项目", "created_at": now()}
    with connect() as database:
        database.execute("INSERT INTO projects VALUES (?,?,?)", tuple(project.values()))
        database.execute('INSERT INTO project_navigation(project_id,position) SELECT ?,COALESCE(MIN(position),0)-1 FROM project_navigation', (project['id'],))
    return project


def create_job(project_id: str, kind: str, payload: dict[str, Any]) -> str:
    from .navigation import removed
    if removed(project_id): raise ValueError('项目已移入回收站，无法创建新任务')
    from .mobile_context import remote_device
    if remote_device.get():
        payload = dict(payload, _mobile_device_id=remote_device.get())
    job_id = uid()
    timestamp = now()
    execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (job_id, project_id, kind, "queued", 0, j(payload), "{}", None, timestamp, timestamp))
    from .task_retry import ensure
    ensure('project',job_id)
    return job_id


def update_job(job_id: str, status: str, progress: int, result: Any = None, error: str | None = None) -> None:
    if status == 'failed':
        from . import task_retry
        attempt = task_retry.current_attempt.get()
        if attempt and attempt.family == 'project' and attempt.job_id == job_id and not attempt.failure_handled:
            # Do not briefly publish a failed status/Windows failure notice for
            # a task that is actually waiting for an automatic retry.
            attempt.failure_handled = True
            if task_retry.schedule('project',job_id,attempt.error or error or '任务未完成',unsafe=attempt.unsafe_replay,partial_result=result):
                return
    execute("UPDATE jobs SET status=?, progress=?, result_json=?, error=?, updated_at=? WHERE id=? "
            "AND status<>'cancelled' AND NOT EXISTS (SELECT 1 FROM deleted_job_records WHERE job_id=jobs.id)",
            (status, progress, j(result or {}), error, now(), job_id))


def update_mastery(topic: str, quiz: float | None = None, feynman: float | None = None,
                   self_rating: float | None = None, difficulty_rating: float | None = None,
                   database=None) -> dict[str, Any]:
    if database is None:
        with connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            return update_mastery(topic,quiz,feynman,self_rating,difficulty_rating,database=connection)
    previous = database.execute("SELECT * FROM mastery WHERE topic=?", (topic,)).fetchone()
    old = dict(previous) if previous else None
    previous_q = (old or {}).get("quiz_score")
    previous_f = (old or {}).get("feynman_score")
    q = (round(.7 * previous_q + .3 * quiz, 1) if previous_q is not None else quiz) if quiz is not None else previous_q
    f = (round(.7 * previous_f + .3 * feynman, 1) if previous_f is not None else feynman) if feynman is not None else previous_f
    s = self_rating if self_rating is not None else (old or {}).get("self_rating")
    difficulty = difficulty_rating if difficulty_rating is not None else (old or {}).get("difficulty_rating")
    # Self-reports describe perceived understanding; they are not measured scores.
    # The legacy NOT NULL column stores 0 when no scored assessment exists.
    # Public profiles expose that situation as score=None instead of mastery=0.
    parts = [(q, .6), (f, .25)]
    total_weight = sum(weight for value, weight in parts if value is not None)
    score = sum(value * weight for value, weight in parts if value is not None) / total_weight if total_weight else 0
    count = (old or {}).get("evidence_count", 0) + 1
    database.execute("INSERT INTO mastery(topic,score,evidence_count,quiz_score,feynman_score,self_rating,updated_at,difficulty_rating) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(topic) DO UPDATE SET "
            "score=excluded.score,evidence_count=excluded.evidence_count,quiz_score=excluded.quiz_score,"
            "feynman_score=excluded.feynman_score,self_rating=excluded.self_rating,"
            "updated_at=excluded.updated_at,difficulty_rating=excluded.difficulty_rating",
            (topic, round(score, 1), count, q, f, s, now(), difficulty))
    return dict(database.execute("SELECT * FROM mastery WHERE topic=?", (topic,)).fetchone())
