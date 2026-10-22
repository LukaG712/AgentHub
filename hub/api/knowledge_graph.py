"""Route module: knowledge_graph.

Provides API endpoints for the Knowledge Graph — vector-based semantic memory.
Supports semantic search, indexing, graph management, and configuration.
"""

import time
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Query

from hub import knowledge_graph
from hub.api.core import _verify_token


async def api_kg_search(
    q: str = Query(..., min_length=1, description="Search query"),
    types: Optional[str] = Query(None, description="Comma-separated entity types to filter (memory,session,message)"),
    k: int = Query(10, ge=1, le=100, description="Maximum results"),
    min_sim: float = Query(0.3, ge=0.0, le=1.0, description="Minimum similarity threshold"),
    context: bool = Query(True, description="Include related entities from graph"),
    _auth: None = Depends(_verify_token),
):
    """Semantic search across all indexed content."""
    entity_types = None
    if types:
        entity_types = [t.strip() for t in types.split(",") if t.strip()]

    if context:
        result = knowledge_graph.search_with_context(
            query=q,
            entity_types=entity_types,
            top_k=k,
            include_related=True,
        )
    else:
        results = knowledge_graph.search(
            query=q,
            entity_types=entity_types,
            top_k=k,
            min_similarity=min_sim,
        )
        result = {
            "query": q,
            "results": results,
            "related_entities": [],
            "graph_stats": {
                "total_nodes": 0,
                "total_edges": 0,
            },
        }

    return result


async def api_kg_stats(
    _auth: None = Depends(_verify_token),
):
    """Get knowledge graph statistics."""
    return knowledge_graph.get_graph_stats()


async def api_kg_index_memories(
    _auth: None = Depends(_verify_token),
):
    """Index all memories into the knowledge graph."""
    count = knowledge_graph.index_all_memories()
    return {"indexed": count, "entity_type": "memory"}


async def api_kg_index_sessions(
    limit: int = Query(50, ge=1, le=200, description="Number of recent sessions to index"),
    _auth: None = Depends(_verify_token),
):
    """Index recent sessions into the knowledge graph."""
    count = knowledge_graph.index_all_sessions(limit=limit)
    return {"indexed": count, "entity_type": "session"}


async def api_kg_index_session(
    session_id: str,
    _auth: None = Depends(_verify_token),
):
    """Index a specific session into the knowledge graph."""
    count = knowledge_graph.index_session(session_id)
    return {"session_id": session_id, "indexed": count}


async def api_kg_rebuild(
    _auth: None = Depends(_verify_token),
):
    """Rebuild the entire knowledge graph index from scratch."""
    result = knowledge_graph.rebuild_index()
    return {
        "status": "rebuilt",
        "memories_indexed": result["memories_indexed"],
        "sessions_indexed": result["sessions_indexed"],
    }


async def api_kg_add_node(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Add or update a node in the knowledge graph."""
    entity_type = body.get("entity_type")
    entity_id = body.get("entity_id")
    content = body.get("content", "")

    if not entity_type:
        raise HTTPException(status_code=400, detail="entity_type is required")
    if not entity_id:
        raise HTTPException(status_code=400, detail="entity_id is required")
    if not content:
        raise HTTPException(status_code=400, detail="content is required")

    result = knowledge_graph.add_node(
        entity_type=entity_type,
        entity_id=entity_id,
        content=content,
        metadata=body.get("metadata"),
    )
    return result


async def api_kg_get_node(
    entity_type: str,
    entity_id: str,
    _auth: None = Depends(_verify_token),
):
    """Get a node from the knowledge graph."""
    node = knowledge_graph.get_node(entity_type, entity_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node '{entity_type}:{entity_id}' not found")
    return node


async def api_kg_delete_node(
    entity_type: str,
    entity_id: str,
    _auth: None = Depends(_verify_token),
):
    """Delete a node from the knowledge graph."""
    deleted = knowledge_graph.remove_node(entity_type, entity_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Node '{entity_type}:{entity_id}' not found")
    return {"deleted": f"{entity_type}:{entity_id}"}


async def api_kg_add_edge(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Add an edge between two nodes."""
    source = body.get("source", {})
    target = body.get("target", {})
    relationship = body.get("relationship", "related")
    weight = body.get("weight", 1.0)

    if not source.get("type") or not source.get("id"):
        raise HTTPException(status_code=400, detail="source.type and source.id are required")
    if not target.get("type") or not target.get("id"):
        raise HTTPException(status_code=400, detail="target.type and target.id are required")

    result = knowledge_graph.add_edge(
        source_type=source["type"],
        source_id=source["id"],
        target_type=target["type"],
        target_id=target["id"],
        relationship=relationship,
        weight=weight,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="One or both nodes not found")
    return result


async def api_kg_get_edges(
    entity_type: str,
    entity_id: str,
    _auth: None = Depends(_verify_token),
):
    """Get all edges connected to a node."""
    edges = knowledge_graph.get_edges(entity_type, entity_id)
    return {"edges": edges}


async def api_kg_backend_status(
    _auth: None = Depends(_verify_token),
):
    """Check the embedding backend status."""
    backend = knowledge_graph.get_backend()
    return {
        "available": backend.is_available(),
        "dimension": backend.dimension(),
        "type": "Ollama" if backend.is_available() else "Simple",
    }


def register(app):
    """Register knowledge_graph routes with the FastAPI app."""
    app.get("/api/knowledge-graph/search")(api_kg_search)
    app.get("/api/knowledge-graph/stats")(api_kg_stats)
    app.post("/api/knowledge-graph/index/memories")(api_kg_index_memories)
    app.post("/api/knowledge-graph/index/sessions")(api_kg_index_sessions)
    app.post("/api/knowledge-graph/index/session/{session_id}")(api_kg_index_session)
    app.post("/api/knowledge-graph/rebuild")(api_kg_rebuild)
    app.post("/api/knowledge-graph/nodes")(api_kg_add_node)
    app.get("/api/knowledge-graph/nodes/{entity_type}/{entity_id}")(api_kg_get_node)
    app.delete("/api/knowledge-graph/nodes/{entity_type}/{entity_id}")(api_kg_delete_node)
    app.post("/api/knowledge-graph/edges")(api_kg_add_edge)
    app.get("/api/knowledge-graph/edges/{entity_type}/{entity_id}")(api_kg_get_edges)
    app.get("/api/knowledge-graph/backend")(api_kg_backend_status)
