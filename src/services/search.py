"""Search and information retrieval service"""

import math
from typing import List, Dict, Tuple, Optional
from contextlib import suppress
from ..config import MAX_VOCAB_SIZE
from ..utils.thai_parser import tokenize
from .neo4j_service import fetch_doc_chunks, graph_retrieve

# Optional embeddings backend (OpenAI via langchain)
with suppress(Exception):
    from langchain_openai import OpenAIEmbeddings  # type: ignore
    _EMBEDDINGS_AVAILABLE = True
try:  # Fallback if import failed
    _EMBEDDINGS_AVAILABLE
except NameError:  # pragma: no cover
    _EMBEDDINGS_AVAILABLE = False


def build_tfidf(texts: List[str], max_vocab: int = MAX_VOCAB_SIZE) -> Tuple[Dict[str, int], List[float], List[List[float]]]:
    """Build TF-IDF vectors for documents"""
    # Document frequency
    df = {}
    docs_tokens = []
    for t in texts:
        toks = tokenize(t)
        docs_tokens.append(toks)
        for w in set(toks):
            df[w] = df.get(w, 0) + 1
    
    N = max(1, len(texts))
    
    # Select top vocabulary terms
    vocab_terms = sorted(df.items(), key=lambda x: (-x[1], x[0]))[:max_vocab]
    vocab = {w: i for i, (w, _) in enumerate(vocab_terms)}
    
    # IDF computation
    idf = [0.0] * len(vocab)
    for w, idx in vocab.items():
        idf[idx] = math.log((N + 1) / (df[w] + 1)) + 1.0
    
    # Create document vectors
    doc_vecs = []
    for toks in docs_tokens:
        tf = {}
        for w in toks:
            if w in vocab:
                tf[w] = tf.get(w, 0) + 1
        vec = [0.0] * len(vocab)
        if tf:
            max_tf = max(tf.values())
            for w, c in tf.items():
                j = vocab[w]
                vec[j] = (c / max_tf) * idf[j]
        doc_vecs.append(vec)
    
    return vocab, idf, doc_vecs


def vectorize_query(q: str, vocab: Dict[str, int], idf: List[float]) -> List[float]:
    """Convert query to TF-IDF vector"""
    toks = tokenize(q)
    tf = {}
    for w in toks:
        if w in vocab:
            tf[w] = tf.get(w, 0) + 1
    vec = [0.0] * len(vocab)
    if tf:
        max_tf = max(tf.values())
        for w, c in tf.items():
            j = vocab[w]
            vec[j] = (c / max_tf) * idf[j]
    return vec


def cosine(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors"""
    num = 0.0
    da = 0.0
    db = 0.0
    for x, y in zip(a, b):
        num += x * y
        da += x * x
        db += y * y
    if da == 0 or db == 0:
        return 0.0
    return num / (math.sqrt(da) * math.sqrt(db))


def _embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    """Embed a list of texts using OpenAI embeddings if available.

    Returns None when embeddings backend is unavailable or errors occur.
    """
    if not _EMBEDDINGS_AVAILABLE:
        return None
    try:
        # Use a small, fast embedding model; configurable via env if needed
        embedder = OpenAIEmbeddings(model="text-embedding-3-small")
        vectors = embedder.embed_documents(texts)
        return vectors
    except Exception:
        return None


def _embed_query(text: str) -> Optional[List[float]]:
    if not _EMBEDDINGS_AVAILABLE:
        return None
    try:
        embedder = OpenAIEmbeddings(model="text-embedding-3-small")
        return embedder.embed_query(text)
    except Exception:
        return None


def hybrid_search(query: str, case_id: Optional[str] = None, k: int = 5) -> Tuple[List[dict], List[dict]]:
    """Perform hybrid search combining vector similarity, TF-IDF, and graph retrieval."""
    # Fetch documents
    docs = fetch_doc_chunks(case_id)
    if not docs:
        return [], []

    # Build TF-IDF and search
    texts = [d["text"] for d in docs]
    vocab, idf, doc_vecs = build_tfidf(texts)
    qv = vectorize_query(query, vocab, idf)

    # TF-IDF scores
    tfidf_scores: List[float] = []
    for dv in doc_vecs:
        tfidf_scores.append(max(0.0, cosine(qv, dv)))

    # Vector embeddings scores (optional)
    vec_scores: Optional[List[float]] = None
    q_emb = _embed_query(query)
    d_embs = _embed_texts(texts) if q_emb is not None else None
    if q_emb is not None and d_embs is not None:
        tmp: List[float] = []
        for ev in d_embs:
            tmp.append(max(0.0, cosine(q_emb, ev)))
        vec_scores = tmp

    # Combine scores: prioritize vector similarity when available
    combined: List[Tuple[int, float]] = []
    for i in range(len(docs)):
        tfidf = tfidf_scores[i] if i < len(tfidf_scores) else 0.0
        if vec_scores is not None:
            vec = vec_scores[i] if i < len(vec_scores) else 0.0
            score = 0.7 * vec + 0.3 * tfidf
        else:
            score = tfidf
        combined.append((i, score))

    # Rank and select top k
    combined.sort(key=lambda x: -x[1])
    top_docs = []
    for idx, score in combined[:k]:
        item = dict(docs[idx])
        item["score"] = score
        top_docs.append(item)

    # Get graph facts
    facts = graph_retrieve(case_id=case_id, limit=20)
    
    return top_docs, facts


def synthesize_answer(query: str, doc_hits: List[dict], facts: List[dict], case_id: Optional[str] = None) -> str:
    """Synthesize answer from document hits and graph facts"""
    lines = []
    
    # Summary from graph facts
    if facts:
        roles = []
        amounts = set()
        dates = set()
        for f in facts:
            if f.get("person") and f.get("role"):
                roles.append(f"{f['person']} ({f['role']})")
            if f.get("amount"):
                amounts.add(f["amount"])
            if f.get("date"):
                dates.add(f["date"])
        
        if roles:
            lines.append("คู่ความ/บทบาท: " + ", ".join(sorted(set(roles))))
        if amounts:
            lines.append("จำนวนเงิน/ค่าจ้างที่ปรากฏ: " + ", ".join(sorted(amounts)))
        if dates:
            lines.append("วันที่เกี่ยวข้อง: " + ", ".join(sorted(dates)))

    # Summary from documents
    if doc_hits:
        lines.append("สาระจากเอกสารที่ใกล้เคียง:")
        for d in doc_hits:
            preview = d["text"].strip().replace("\n", " ")
            if len(preview) > 180:
                preview = preview[:180] + "..."
            lines.append(f"- {preview}")

    # Citations
    if doc_hits:
        lines.append("อ้างอิง:")
        for d in doc_hits:
            cid = d.get("caseId") or case_id or "-"
            page = d.get("page") or "-"
            lines.append(f"- [Case: {cid}, page: {page}] {d.get('chunkId', '')}")

    if not lines:
        lines.append("ไม่พบข้อมูลที่เกี่ยวข้องเพียงพอสำหรับคำถามนี้")

    return "\n".join(lines)
