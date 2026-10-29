"""RAG: read files -> chunk -> embed locally -> store in Chroma -> semantic search."""

import re
from functools import cache
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import CHUNK_WORDS, DATA_DIR, EMBED_MODEL

SUPPORTED = {".pdf", ".docx", ".md", ".txt"}


# ---------- loading ----------

def load_sections(path: Path) -> list[dict]:
    """Returns [{heading, page, text}] so search results can cite where they came from."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        import pymupdf

        with pymupdf.open(path) as pdf:
            return [{"heading": "", "page": i, "text": p.get_text()} for i, p in enumerate(pdf, 1) if p.get_text().strip()]
    if ext == ".docx":
        import docx

        sections, heading, buf = [], "", []
        for para in docx.Document(str(path)).paragraphs:
            if para.style is not None and para.style.name.lower().startswith("heading"):
                sections.append({"heading": heading, "page": 0, "text": "\n".join(buf)})
                heading, buf = para.text.strip(), []
            else:
                buf.append(para.text)
        sections.append({"heading": heading, "page": 0, "text": "\n".join(buf)})
        return [s for s in sections if s["text"].strip()]
    if ext in {".md", ".txt"}:
        sections, heading, buf = [], "", []
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r"^#{1,6}\s+(.*)", line)
            if m:
                sections.append({"heading": heading, "page": 0, "text": "\n".join(buf)})
                heading, buf = m.group(1).strip(), []
            else:
                buf.append(line)
        sections.append({"heading": heading, "page": 0, "text": "\n".join(buf)})
        return [s for s in sections if s["text"].strip()]
    raise ValueError(f"Unsupported file type: {ext}")


def chunk(sections: list[dict]) -> list[dict]:
    """Split each section into ~CHUNK_WORDS-word pieces, keeping its heading/page."""
    chunks = []
    for s in sections:
        words = s["text"].split()
        for i in range(0, len(words), CHUNK_WORDS):
            chunks.append({**s, "text": " ".join(words[i:i + CHUNK_WORDS])})
    return chunks


# ---------- embeddings + store ----------

@cache
def _embedder():
    from fastembed import TextEmbedding

    return TextEmbedding(EMBED_MODEL, cache_dir=str(DATA_DIR / "models"))


def embed(texts: list[str]) -> list[list[float]]:
    return [v.tolist() for v in _embedder().embed(texts)]


@cache
def _collection():
    client = chromadb.PersistentClient(path=str(DATA_DIR / "chroma"), settings=ChromaSettings(anonymized_telemetry=False))
    return client.get_or_create_collection("materials", metadata={"hnsw:space": "cosine"})


def index_file(path: Path, doc_id: int, goal_id: int, filename: str) -> int:
    chunks = chunk(load_sections(path))
    if not chunks:
        raise ValueError(f"No text found in {filename}")
    _collection().add(
        ids=[f"{doc_id}-{i}" for i in range(len(chunks))],
        documents=[c["text"] for c in chunks],
        embeddings=embed([f"{c['heading']}\n{c['text']}" for c in chunks]),
        metadatas=[{"goal_id": goal_id, "doc_id": doc_id, "filename": filename, "heading": c["heading"], "page": c["page"]}
                   for c in chunks],
    )
    return len(chunks)


def delete_goal(goal_id: int) -> None:
    _collection().delete(where={"goal_id": goal_id})


def goal_chunks(goal_id: int) -> list[dict]:
    """A goal's chunks in upload order: [{text, filename, heading, page}]."""
    res = _collection().get(where={"goal_id": goal_id})
    order = sorted(range(len(res["ids"])), key=lambda i: tuple(map(int, res["ids"][i].split("-"))))
    return [{"text": res["documents"][i], **res["metadatas"][i]} for i in order]


def goal_text(goal_id: int, max_words: int = 8000) -> str:
    """A goal's material as one text (trimmed), for topic extraction."""
    parts, total = [], 0
    for c in goal_chunks(goal_id):
        parts.append(f"[{c['filename']} | {c['heading']}]\n{c['text']}")
        total += len(c["text"].split())
        if total > max_words:
            break
    return "\n\n".join(parts)


def search(query: str, goal_id: int | None = None, k: int = 5) -> list[dict]:
    col = _collection()
    if col.count() == 0:
        return []
    res = col.query(
        query_embeddings=embed([query]),
        n_results=min(k, col.count()),
        where={"goal_id": goal_id} if goal_id else None,
    )
    return [
        {"text": text, "filename": m["filename"], "heading": m["heading"], "page": m["page"]}
        for text, m in zip(res["documents"][0], res["metadatas"][0])
    ]


def delete_all() -> None:
    col = _collection()
    ids = col.get()["ids"]
    if ids:
        col.delete(ids=ids)
