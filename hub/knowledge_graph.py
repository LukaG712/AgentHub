"""Knowledge Graph — vector-based semantic memory layer.

Provides semantic search across memories, sessions, and messages using
vector embeddings stored in SQLite. Uses Ollama's embeddings API as the
default embedding backend, with a fallback to a simple TF-IDF-like approach
when Ollama is unavailable.

Key features:
- Embed and store text chunks from memories, sessions, and messages
- Semantic similarity search using cosine similarity
- Graph relationships between related entities (memories ↔ sessions ↔ messages)
- Automatic re-indexing when content changes
- Configurable embedding model and dimensions
"""

import json
import logging
import math
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from hub import memory as memory_module
from hub.config import load_config

logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────────

_DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
_DEFAULT_EMBEDDING_DIM = 768  # nomic-embed-text dimension
_DEFAULT_OLLAMA_URL = "http://localhost:11434"
_DEFAULT_TIMEOUT = 30

# Chunking settings
_MAX_CHUNK_SIZE = 500  # characters per chunk
_CHUNK_OVERLAP = 50  # overlap between chunks

# Search settings
_DEFAULT_TOP_K = 10
_DEFAULT_SIMILARITY_THRESHOLD = 0.3


class EmbeddingBackend:
    """Abstract embedding backend interface."""

    def embed(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError

    def dimension(self) -> int:
        raise NotImplementedError

    def is_available(self) -> bool:
        raise NotImplementedError


class OllamaEmbeddingBackend(EmbeddingBackend):
    """Uses Ollama's /api/embeddings endpoint for generating vectors."""

    def __init__(self, base_url: str = _DEFAULT_OLLAMA_URL, model: str = _DEFAULT_EMBEDDING_MODEL, timeout: int = _DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._dim_cache: Optional[int] = None
        self._available_cache: Optional[bool] = None
        self._check_time: float = 0

    def is_available(self) -> bool:
        now = time.time()
        if self._available_cache is not None and (now - self._check_time) < 60:
            return self._available_cache
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                model_names = [m.get("name", "").split(":")[0] for m in models]
                self._available_cache = self.model.split(":")[0] in model_names
                self._check_time = now
                return self._available_cache
        except (requests.RequestException, json.JSONDecodeError):
            pass
        self._available_cache = False
        self._check_time = now
        return False

    def embed(self, texts: List[str]) -> List[List[float]]:
        embeddings = []
        for text in texts:
            emb = self._embed_single(text)
            embeddings.append(emb)
        return embeddings

    def _embed_single(self, text: str) -> List[float]:
        try:
            resp = requests.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                embedding = data.get("embedding", [])
                if embedding:
                    self._dim_cache = len(embedding)
                    return embedding
        except (requests.RequestException, json.JSONDecodeError) as e:
            logger.warning("Ollama embedding failed: %s", e)
        # Fallback: return zero vector
        dim = self._dim_cache or _DEFAULT_EMBEDDING_DIM
        return [0.0] * dim

    def dimension(self) -> int:
        if self._dim_cache:
            return self._dim_cache
        # Try to get dimension from a test embedding
        if self.is_available():
            emb = self._embed_single("test")
            if emb:
                return len(emb)
        return _DEFAULT_EMBEDDING_DIM


class SimpleEmbeddingBackend(EmbeddingBackend):
    """Fallback backend using TF-IDF-like hashing for when Ollama is unavailable.

    This produces low-quality embeddings that enable basic similarity search
    without external dependencies. Useful for development and testing.
    """

    _DIM = 128

    def is_available(self) -> bool:
        return True

    def dimension(self) -> int:
        return self._DIM

    def embed(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_single(text) for text in texts]

    def _embed_single(self, text: str) -> List[float]:
        vec = [0.0] * self._DIM
        words = text.lower().split()
        for word in words:
            # Simple hash-based bucketing
            for i, ch in enumerate(word):
                idx = (hash(word) + i) % self._DIM
                vec[idx] += 1.0 / math.sqrt(len(word) + 1)
        # Normalize
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        vec = [v / norm for v in vec]
        return vec


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (norm_a * norm_b)


# ─── Database ───────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_DB_PATH = _DATA_DIR / "hub.db"  # Same DB as memory.py

_local = threading.local()


def _get_db_path() -> Path:
    path = os.environ.get("HUB_DB_PATH")
    if path:
        return Path(path)
    return _DB_PATH


def _get_connection() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        db_path = _get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        max_retries = 5
        for attempt in range(max_retries):
            try:
                conn = sqlite3.connect(str(db_path), timeout=10.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.row_factory = sqlite3.Row
                _ensure_schema(conn)
                _local.conn = conn
                break
            except sqlite3.OperationalError:
                if attempt == max_retries - 1:
                    raise
                time.sleep(0.1 * (attempt + 1))
    return _local.conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create knowledge graph tables if they don't exist."""
    cursor = conn.cursor()

    # Nodes: stored entities with their embeddings
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kg_nodes (
            id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            content TEXT NOT NULL,
            embedding BLOB NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # Edges: relationships between nodes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kg_edges (
            id TEXT PRIMARY KEY,
            source_node_id TEXT NOT NULL,
            target_node_id TEXT NOT NULL,
            relationship TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_node_id) REFERENCES kg_nodes(id) ON DELETE CASCADE,
            FOREIGN KEY (target_node_id) REFERENCES kg_nodes(id) ON DELETE CASCADE
        )
    """)

    # Indexes for fast lookups
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_nodes_type ON kg_nodes(entity_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_nodes_entity ON kg_nodes(entity_type, entity_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_edges_source ON kg_edges(source_node_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_edges_target ON kg_edges(target_node_id)")

    conn.commit()


# ─── Global backend ─────────────────────────────────────────────────────────

_backend_lock = threading.Lock()
_backend: Optional[EmbeddingBackend] = None


def get_backend() -> EmbeddingBackend:
    """Get the current embedding backend, initializing if needed."""
    global _backend
    if _backend is not None:
        return _backend

    with _backend_lock:
        if _backend is not None:
            return _backend

        # Try Ollama first
        try:
            config = load_config()
            kg_cfg = config.get("knowledge_graph", {})
            ollama_cfg = config.get("ollama", {})

            base_url = kg_cfg.get("embedding_url", ollama_cfg.get("base_url", _DEFAULT_OLLAMA_URL))
            model = kg_cfg.get("embedding_model", _DEFAULT_EMBEDDING_MODEL)
            timeout = kg_cfg.get("embedding_timeout", _DEFAULT_TIMEOUT)

            ollama_backend = OllamaEmbeddingBackend(base_url=base_url, model=model, timeout=timeout)
            if ollama_backend.is_available():
                _backend = ollama_backend
                logger.info("Knowledge graph using Ollama embeddings: %s", model)
                return _backend
        except Exception as e:
            logger.debug("Ollama embeddings not available: %s", e)

        # Fallback to simple backend
        _backend = SimpleEmbeddingBackend()
        logger.info("Knowledge graph using simple embeddings (Ollama unavailable)")
        return _backend


# ─── Node operations ────────────────────────────────────────────────────────

def _serialize_vector(vec: List[float]) -> bytes:
    """Serialize a float vector to bytes for SQLite BLOB storage."""
    import struct
    return struct.pack(f'{len(vec)}f', *vec)


def _deserialize_vector(data: bytes) -> List[float]:
    """Deserialize a float vector from SQLite BLOB."""
    import struct
    n = len(data) // 4
    return list(struct.unpack(f'{n}f', data))


def add_node(
    entity_type: str,
    entity_id: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Add or update a node in the knowledge graph.

    Args:
        entity_type: Type of entity (memory, session, message, note, file)
        entity_id: Unique ID of the entity
        content: Text content to embed
        metadata: Optional metadata dict

    Returns:
        The created/updated node dict.
    """
    backend = get_backend()
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()

    # Chunk content if too long
    chunks = _chunk_text(content, _MAX_CHUNK_SIZE, _CHUNK_OVERLAP)

    # Embed all chunks
    embeddings = backend.embed(chunks)

    # Average embeddings to get a single vector for the node
    avg_embedding = _average_vectors(embeddings)

    # Serialize
    embedding_blob = _serialize_vector(avg_embedding)
    metadata_json = json.dumps(metadata) if metadata else None

    node_id = str(uuid.uuid4())

    # Upsert node
    existing = conn.execute(
        "SELECT id FROM kg_nodes WHERE entity_type = ? AND entity_id = ?",
        (entity_type, entity_id),
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE kg_nodes SET id = ?, content = ?, embedding = ?, metadata = ?, updated_at = ?
               WHERE entity_type = ? AND entity_id = ?""",
            (node_id, content, embedding_blob, metadata_json, now, entity_type, entity_id),
        )
        # Remove old edges pointing to the old node ID
        conn.execute(
            "DELETE FROM kg_edges WHERE source_node_id = ? OR target_node_id = ?",
            (existing["id"], existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO kg_nodes (id, entity_type, entity_id, content, embedding, metadata, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (node_id, entity_type, entity_id, content, embedding_blob, metadata_json, now, now),
        )

    conn.commit()

    return {
        "id": node_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "content": content,
        "metadata": metadata,
        "embedding_dim": len(avg_embedding),
        "chunks": len(chunks),
    }


def remove_node(entity_type: str, entity_id: str) -> bool:
    """Remove a node from the knowledge graph."""
    conn = _get_connection()
    cursor = conn.execute(
        "DELETE FROM kg_nodes WHERE entity_type = ? AND entity_id = ?",
        (entity_type, entity_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_node(entity_type: str, entity_id: str) -> Optional[Dict[str, Any]]:
    """Get a node from the knowledge graph."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT * FROM kg_nodes WHERE entity_type = ? AND entity_id = ?",
        (entity_type, entity_id),
    ).fetchone()
    if row is None:
        return None
    return _node_to_dict(row)


def _node_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["embedding_dim"] = len(d["embedding"]) // 4 if d["embedding"] else 0
    d["metadata"] = json.loads(d["metadata"]) if d["metadata"] else None
    # Don't return raw bytes
    d.pop("embedding", None)
    return d


# ─── Edge operations ────────────────────────────────────────────────────────

def add_edge(
    source_type: str, source_id: str,
    target_type: str, target_id: str,
    relationship: str, weight: float = 1.0,
) -> Optional[Dict[str, Any]]:
    """Add an edge between two nodes.

    Args:
        source_type/source_id: Source node entity type and ID
        target_type/target_id: Target node entity type and ID
        relationship: Relationship type (related, mentions, depends_on, etc.)
        weight: Edge weight (0.0 to 1.0)

    Returns:
        The created edge dict, or None if either node doesn't exist.
    """
    conn = _get_connection()

    source = conn.execute(
        "SELECT id FROM kg_nodes WHERE entity_type = ? AND entity_id = ?",
        (source_type, source_id),
    ).fetchone()

    target = conn.execute(
        "SELECT id FROM kg_nodes WHERE entity_type = ? AND entity_id = ?",
        (target_type, target_id),
    ).fetchone()

    if source is None or target is None:
        return None

    edge_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """INSERT INTO kg_edges (id, source_node_id, target_node_id, relationship, weight, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (edge_id, source["id"], target["id"], relationship, weight, now),
    )
    conn.commit()

    return {
        "id": edge_id,
        "source": {"type": source_type, "id": source_id},
        "target": {"type": target_type, "id": target_id},
        "relationship": relationship,
        "weight": weight,
    }


def get_edges(entity_type: str, entity_id: str) -> List[Dict[str, Any]]:
    """Get all edges connected to a node."""
    conn = _get_connection()
    node = conn.execute(
        "SELECT id FROM kg_nodes WHERE entity_type = ? AND entity_id = ?",
        (entity_type, entity_id),
    ).fetchone()

    if node is None:
        return []

    rows = conn.execute(
        """SELECT e.*,
                  sn.entity_type AS source_type, sn.entity_id AS source_entity_id,
                  tn.entity_type AS target_type, tn.entity_id AS target_entity_id
           FROM kg_edges e
           JOIN kg_nodes sn ON sn.id = e.source_node_id
           JOIN kg_nodes tn ON tn.id = e.target_node_id
           WHERE e.source_node_id = ? OR e.target_node_id = ?""",
        (node["id"], node["id"]),
    ).fetchall()

    results = []
    for row in rows:
        d = dict(row)
        results.append({
            "id": d["id"],
            "source": {"type": d["source_type"], "id": d["source_entity_id"]},
            "target": {"type": d["target_type"], "id": d["target_entity_id"]},
            "relationship": d["relationship"],
            "weight": d["weight"],
            "created_at": d["created_at"],
        })
    return results


# ─── Semantic Search ────────────────────────────────────────────────────────

def search(
    query: str,
    entity_types: Optional[List[str]] = None,
    top_k: int = _DEFAULT_TOP_K,
    min_similarity: float = _DEFAULT_SIMILARITY_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Semantic search across all indexed content.

    Args:
        query: Search query text
        entity_types: Filter by entity types (memory, session, message, etc.)
        top_k: Maximum number of results
        min_similarity: Minimum cosine similarity threshold (0.0 to 1.0)

    Returns:
        List of results with similarity scores, sorted by relevance.
    """
    backend = get_backend()
    conn = _get_connection()

    # Embed the query
    query_embedding = backend.embed([query])[0]
    query_blob = _serialize_vector(query_embedding)

    # Build query
    conditions = []
    params: List[Any] = []

    if entity_types:
        placeholders = ", ".join("?" for _ in entity_types)
        conditions.append(f"entity_type IN ({placeholders})")
        params.extend(entity_types)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    # Fetch all nodes (we compute similarity in Python)
    # For large datasets, this could be optimized with ANN indexes
    rows = conn.execute(
        f"SELECT * FROM kg_nodes {where} ORDER BY created_at DESC LIMIT ?",
        params + [top_k * 5],  # Fetch more to allow filtering by similarity
    ).fetchall()

    results = []
    for row in rows:
        row_dict = dict(row)
        node_embedding = _deserialize_vector(row_dict["embedding"])

        similarity = cosine_similarity(query_embedding, node_embedding)

        if similarity >= min_similarity:
            metadata = json.loads(row_dict["metadata"]) if row_dict["metadata"] else None
            results.append({
                "node_id": row_dict["id"],
                "entity_type": row_dict["entity_type"],
                "entity_id": row_dict["entity_id"],
                "content": row_dict["content"],
                "metadata": metadata,
                "similarity": round(similarity, 4),
                "created_at": row_dict["created_at"],
            })

    # Sort by similarity descending
    results.sort(key=lambda r: r["similarity"], reverse=True)
    return results[:top_k]


def search_with_context(
    query: str,
    entity_types: Optional[List[str]] = None,
    top_k: int = _DEFAULT_TOP_K,
    include_related: bool = True,
) -> Dict[str, Any]:
    """Semantic search with related entity expansion.

    Returns search results plus related entities from the graph,
    providing richer context for agent responses.

    Args:
        query: Search query text
        entity_types: Filter by entity types
        top_k: Maximum number of primary results
        include_related: Whether to include connected entities

    Returns:
        Dict with 'results', 'related_entities', and 'graph_stats'.
    """
    primary_results = search(query, entity_types, top_k)

    related_entities = []
    if include_related and primary_results:
        seen = set()
        for result in primary_results[:5]:  # Only expand top 5
            edges = get_edges(result["entity_type"], result["entity_id"])
            for edge in edges:
                target = edge["target"]
                key = f"{target['type']}:{target['id']}"
                if key not in seen and key != f"{result['entity_type']}:{result['entity_id']}":
                    seen.add(key)
                    # Fetch the target node's content
                    target_node = get_node(target["type"], target["id"])
                    if target_node:
                        related_entities.append({
                            "entity_type": target["type"],
                            "entity_id": target["id"],
                            "content": target_node.get("content", ""),
                            "relationship": edge["relationship"],
                            "weight": edge["weight"],
                        })

    # Graph statistics
    conn = _get_connection()
    node_count = conn.execute("SELECT COUNT(*) AS cnt FROM kg_nodes").fetchone()["cnt"]
    edge_count = conn.execute("SELECT COUNT(*) AS cnt FROM kg_edges").fetchone()["cnt"]

    return {
        "query": query,
        "results": primary_results,
        "related_entities": related_entities,
        "graph_stats": {
            "total_nodes": node_count,
            "total_edges": edge_count,
        },
    }


# ─── Indexing helpers ────────────────────────────────────────────────────────

def index_all_memories() -> int:
    """Index all memories from the memory store into the knowledge graph."""
    count = 0
    memories = memory_module.list_memories(limit=1000)
    for mem in memories:
        content = mem.get("content", "")
        if not content.strip():
            continue
        metadata = {
            "agent_id": mem.get("agent_id"),
            "project_path": mem.get("project_path"),
            "session_id": mem.get("session_id"),
            "tags": mem.get("tags"),
        }
        add_node("memory", mem["id"], content, metadata)
        count += 1
    logger.info("Indexed %d memories into knowledge graph", count)
    return count


def index_session(session_id: str) -> int:
    """Index all messages from a session into the knowledge graph."""
    count = 0
    messages = memory_module.get_session_messages(session_id)
    for msg in messages:
        content = msg.get("content", "")
        if not content.strip():
            continue
        metadata = {
            "role": msg.get("role"),
            "bot_id": msg.get("bot_id"),
            "run_id": msg.get("run_id"),
        }
        add_node("message", msg["id"], content, metadata)
        count += 1

    # Link messages to session
    session = memory_module.get_session(session_id)
    if session:
        session_content = session.get("title", "") + " " + session.get("last_message_preview", "")
        if session_content.strip():
            add_node("session", session_id, session_content, {
                "agent_id": session.get("agent_id"),
                "project_path": session.get("project_path"),
            })
            # Link messages to session
            for msg in messages:
                add_edge("session", session_id, "message", msg["id"], "contains")

    logger.info("Indexed %d messages for session %s", count, session_id)
    return count


def index_all_sessions(limit: int = 50) -> int:
    """Index recent sessions into the knowledge graph."""
    sessions = memory_module.list_sessions(limit=limit)
    total = 0
    for session in sessions:
        total += index_session(session["id"])
    return total


def rebuild_index() -> Dict[str, int]:
    """Rebuild the entire knowledge graph index from scratch."""
    conn = _get_connection()
    conn.execute("DELETE FROM kg_edges")
    conn.execute("DELETE FROM kg_nodes")
    conn.commit()

    memories_count = index_all_memories()
    sessions_count = index_all_sessions()

    return {
        "memories_indexed": memories_count,
        "sessions_indexed": sessions_count,
    }


# ─── Utility functions ──────────────────────────────────────────────────────

def _chunk_text(text: str, max_size: int = _MAX_CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks for embedding."""
    if len(text) <= max_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_size
        chunk = text[start:end]
        # Try to break at sentence boundary
        if end < len(text):
            last_period = chunk.rfind(".")
            last_newline = chunk.rfind("\n")
            break_point = max(last_period, last_newline)
            if break_point > max_size // 2:
                chunk = chunk[:break_point + 1]
                end = start + len(chunk)
        chunks.append(chunk.strip())
        start = end - overlap
        if start <= 0:
            start = end  # Avoid infinite loop

    return [c for c in chunks if c]


def _average_vectors(vectors: List[List[float]]) -> List[float]:
    """Average a list of vectors into a single vector."""
    if not vectors:
        return []
    if len(vectors) == 1:
        return vectors[0]

    dim = len(vectors[0])
    avg = [0.0] * dim
    for vec in vectors:
        for i in range(dim):
            avg[i] += vec[i]
    avg = [v / len(vectors) for v in avg]

    # Normalize
    norm = math.sqrt(sum(v * v for v in avg)) or 1.0
    return [v / norm for v in avg]


def get_graph_stats() -> Dict[str, Any]:
    """Get statistics about the knowledge graph."""
    conn = _get_connection()

    node_count = conn.execute("SELECT COUNT(*) AS cnt FROM kg_nodes").fetchone()["cnt"]
    edge_count = conn.execute("SELECT COUNT(*) AS cnt FROM kg_edges").fetchone()["cnt"]

    # Nodes by type
    type_rows = conn.execute(
        "SELECT entity_type, COUNT(*) AS cnt FROM kg_nodes GROUP BY entity_type"
    ).fetchall()
    nodes_by_type = {row["entity_type"]: row["cnt"] for row in type_rows}

    # Edges by relationship
    rel_rows = conn.execute(
        "SELECT relationship, COUNT(*) AS cnt FROM kg_edges GROUP BY relationship"
    ).fetchall()
    edges_by_rel = {row["relationship"]: row["cnt"] for row in rel_rows}

    # Backend info
    backend = get_backend()
    backend_name = "Ollama" if isinstance(backend, OllamaEmbeddingBackend) else "Simple"
    backend_available = backend.is_available()

    return {
        "total_nodes": node_count,
        "total_edges": edge_count,
        "nodes_by_type": nodes_by_type,
        "edges_by_relationship": edges_by_rel,
        "backend": backend_name,
        "backend_available": backend_available,
        "embedding_dim": backend.dimension(),
    }


def close_connection() -> None:
    """Close the thread-local database connection."""
    if hasattr(_local, "conn") and _local.conn is not None:
        _local.conn.close()
        _local.conn = None
