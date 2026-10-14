CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE users (id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE COLLATE NOCASE,password_hash TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('active','disabled')),role TEXT CHECK(role IS NULL OR role IN ('admin','editor','viewer')),must_change_password INTEGER NOT NULL DEFAULT 0,temporary_password_expires_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), token_hash TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL, revoked_at TEXT, created_at TEXT NOT NULL);
CREATE TABLE api_keys (id TEXT PRIMARY KEY,name TEXT NOT NULL,key_prefix TEXT NOT NULL,key_hash TEXT NOT NULL UNIQUE,scopes_json TEXT NOT NULL,expires_at TEXT,revoked_at TEXT,created_by TEXT NOT NULL REFERENCES users(id),last_used_at TEXT,created_at TEXT NOT NULL);
CREATE TABLE knowledge_bases (id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE COLLATE NOCASE,description TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','deleting','deleted','delete_failed')),chunk_size INTEGER NOT NULL,chunk_overlap INTEGER NOT NULL,chunk_strategy TEXT NOT NULL DEFAULT 'recursive' CHECK(chunk_strategy IN ('recursive','structure')),created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE documents (id TEXT PRIMARY KEY,knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),filename TEXT NOT NULL,stored_filename TEXT NOT NULL,sha256 TEXT NOT NULL,size_bytes INTEGER NOT NULL,chunk_count INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL CHECK(status IN ('pending','indexing','ready','failed','deleting','deleted','delete_failed')),error_message TEXT,created_by TEXT NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(knowledge_base_id,sha256));
CREATE INDEX documents_kb_idx ON documents(knowledge_base_id,created_at DESC);
CREATE TABLE audit_events (id TEXT PRIMARY KEY,actor_type TEXT NOT NULL,actor_id TEXT,action TEXT NOT NULL,resource_type TEXT NOT NULL,resource_id TEXT,request_id TEXT NOT NULL,created_at TEXT NOT NULL,detail_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE graph_builds (
                id TEXT PRIMARY KEY,
                knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),
                requested_by TEXT REFERENCES users(id),
                status TEXT NOT NULL CHECK(status IN ('queued','running','ready','failed')),
                extractor_model TEXT NOT NULL, extractor_version TEXT NOT NULL,
                schema_version INTEGER NOT NULL, requested_at TEXT NOT NULL,
                started_at TEXT, finished_at TEXT, error_code TEXT
            );

CREATE TABLE graph_document_states (
                knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),
                document_id TEXT NOT NULL REFERENCES documents(id),
                build_id TEXT REFERENCES graph_builds(id), source_sha256 TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('not_built','building','ready','stale','failed')),
                extractor_model TEXT, extractor_version TEXT, indexed_at TEXT,
                error_code TEXT, updated_at TEXT NOT NULL,
                PRIMARY KEY(knowledge_base_id, document_id)
            );

CREATE TABLE entities (
                id TEXT PRIMARY KEY, knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),
                canonical_name TEXT NOT NULL, normalized_name TEXT NOT NULL, entity_type TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(knowledge_base_id, normalized_name, entity_type), UNIQUE(knowledge_base_id, id)
            );

CREATE TABLE entity_aliases (
                id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities(id), normalized_alias TEXT NOT NULL,
                UNIQUE(entity_id, normalized_alias)
            );

CREATE TABLE relations (
                id TEXT PRIMARY KEY, knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),
                subject_entity_id TEXT NOT NULL, predicate TEXT NOT NULL, object_entity_id TEXT NOT NULL,
                confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
                extractor_model TEXT NOT NULL, extractor_version TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(knowledge_base_id, subject_entity_id, predicate, object_entity_id),
                UNIQUE(knowledge_base_id, id),
                FOREIGN KEY(knowledge_base_id, subject_entity_id) REFERENCES entities(knowledge_base_id, id),
                FOREIGN KEY(knowledge_base_id, object_entity_id) REFERENCES entities(knowledge_base_id, id)
            );

CREATE TABLE entity_mentions (
                id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, knowledge_base_id TEXT NOT NULL,
                document_id TEXT NOT NULL REFERENCES documents(id), chunk_id TEXT NOT NULL,
                start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL,
                UNIQUE(entity_id, chunk_id, start_offset, end_offset),
                FOREIGN KEY(knowledge_base_id, entity_id) REFERENCES entities(knowledge_base_id, id)
            );

CREATE TABLE relation_mentions (
                id TEXT PRIMARY KEY, relation_id TEXT NOT NULL, knowledge_base_id TEXT NOT NULL,
                document_id TEXT NOT NULL REFERENCES documents(id), chunk_id TEXT NOT NULL,
                build_id TEXT NOT NULL REFERENCES graph_builds(id),
                UNIQUE(relation_id, chunk_id, build_id),
                FOREIGN KEY(knowledge_base_id, relation_id) REFERENCES relations(knowledge_base_id, id)
            );

CREATE INDEX graph_builds_kb_idx ON graph_builds(knowledge_base_id, status, requested_at DESC);

CREATE INDEX graph_document_states_kb_idx ON graph_document_states(knowledge_base_id, status, updated_at DESC);

CREATE INDEX entities_kb_name_idx ON entities(knowledge_base_id, normalized_name, entity_type);

CREATE INDEX relations_kb_subject_idx ON relations(knowledge_base_id, subject_entity_id, predicate);

CREATE INDEX relations_kb_object_idx ON relations(knowledge_base_id, object_entity_id, predicate);

CREATE INDEX entity_mentions_kb_document_idx ON entity_mentions(knowledge_base_id, document_id, chunk_id);

CREATE INDEX relation_mentions_kb_document_idx ON relation_mentions(knowledge_base_id, document_id, chunk_id);
