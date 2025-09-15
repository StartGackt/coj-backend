import os
import re
import hashlib
from typing import Optional, List

from dotenv import load_dotenv
from neo4j import GraphDatabase

import math
from collections import deque

# API
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# 1) Load environment and Neo4j config
load_dotenv()
URI = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
AUTH = (
    os.getenv("NEO4J_USER", "neo4j"),
    os.getenv("NEO4J_PASSWORD", "12345678"),
)


# 2) Ontology / Schema (minimal, focused)
ALLOWED_NODE_LABELS = [
    "Person",
    "CourtCase",
    "EmploymentContract",
    "MoneyAmount",
    "Date",
    "LegalRole",
    "LegalTerm",
    "Position",
    "Entity",
    "Group",
    "Section",
    "Section_desc",

]

ALLOWED_REL_TYPES = [
    "PARTY",        # (Person)-[:PARTY]->(CourtCase)
    "HAS_ROLE",     # (Person)-[:HAS_ROLE]->(LegalRole)
    "EMPLOYED_BY",  # (Person)-[:EMPLOYED_BY]->(EmploymentContract|Organization|Person)
    "HAS_AMOUNT",   # (* )-[:HAS_AMOUNT]->(MoneyAmount)
    "CLAIMS",       # (Person)-[:CLAIMS]->(CourtCase)
    "OCCURRED_ON",  # (* )-[:OCCURRED_ON]->(Date)
    "SECTION",      # (Section)-[:SECTION]->(Group) 
    
]

# 3) Thai parsing helpers (dates, amounts)
THAI_MONTHS = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4,
    "พฤษภาคม": 5, "มิถุนายน": 6, "กรกฎาคม": 7, "สิงหาคม": 8,
    "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
}


def parse_thai_amount(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"([0-9][0-9,\.]*)\s*บาท", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except Exception:
        return None


def parse_thai_date_iso(text: str) -> Optional[str]:
    if not text:
        return None
    s = text.strip()
    m = re.search(r"(\d{1,2})\s+([\u0E00-\u0E7F]+)\s+(\d{4})", s)
    if m:
        d = int(m.group(1))
        mon_name = m.group(2)
        y = int(m.group(3))
        mon = THAI_MONTHS.get(mon_name)
        if mon:
            if y > 2400:
                y -= 543
            return f"{y:04d}-{mon:02d}-{d:02d}"
    m2 = re.search(r"([\u0E00-\u0E7F]+)\s+(\d{4})", s)
    if m2:
        mon_name = m2.group(1)
        y = int(m2.group(2))
        mon = THAI_MONTHS.get(mon_name)
        if mon:
            if y > 2400:
                y -= 543
            return f"{y:04d}-{mon:02d}"
    return None


# 4) Minimal graph document classes (rule-based extraction)
class SimpleNode:
    def __init__(self, id: str, type: str):
        self.id = id
        self.type = type


class SimpleRel:
    def __init__(self, source: SimpleNode, target: SimpleNode, type: str):
        self.source = source
        self.target = target
        self.type = type


class SimpleGraphDocument:
    def __init__(self, nodes: List[SimpleNode], relationships: List[SimpleRel]):
        self.nodes = nodes
        self.relationships = relationships


# 5) Rule-based extraction (no LLM, minimal and predictable)
def rule_based_extract(text: str) -> List[SimpleGraphDocument]:
    nodes: List[SimpleNode] = []
    rels: List[SimpleRel] = []
    index = {}

    def get_node(name: str, typ: str) -> SimpleNode:
        key = (name, typ)
        if key not in index:
            n = SimpleNode(name, typ)
            index[key] = n
            nodes.append(n)
        return index[key]

    s = text
    s = normalize_thai_digits(text)

    m_section = re.search(r"มาตรา\s*(\d+)", s)
    # Parties
    plaintiff = get_node("โจทก์", "Person") if re.search(r"โจทก(์)?", s) else None
    defendant = get_node("จำเลย", "Person") if "จำเลย" in s else None

    # Employment
    if any(kw in s for kw in ["จ้าง", "เข้าทำงาน", "ลูกจ้าง", "ทำงาน"]):
        contract = get_node("สัญญาจ้างงาน", "EmploymentContract")
        if plaintiff:
            rels.append(SimpleRel(plaintiff, contract, "EMPLOYED_BY"))

    # Wages
    if "ค่าจ้าง" in s or "เงินเดือน" in s:
        amt = parse_thai_amount(s)
        if amt is not None:
            money = get_node(f"{int(amt):,} บาท", "MoneyAmount")
            term = get_node("ค่าจ้าง", "LegalTerm")
            rels.append(SimpleRel(term, money, "HAS_AMOUNT"))

    # Dates
    iso = parse_thai_date_iso(s)
    if iso:
        date = get_node(iso, "Date")
        if plaintiff:
            rels.append(SimpleRel(plaintiff, date, "OCCURRED_ON"))

    # --- Group ---
    group = None
    m_group = re.search(r"หมวด\s*(\d+)", s)
    if m_group:
        group_no = m_group.group(1)
        group = get_node(f"หมวด {group_no}", "Group")

    # --- Section + Section_desc ---
    section = None
    m_section = re.search(r"มาตรา\s*(\d+)(.*)", s)
    if m_section:
        sec_no = m_section.group(1)
        desc_text = m_section.group(2).strip()
        section = get_node(f"มาตรา {sec_no}", "Section")
        if desc_text:
            desc = get_node(desc_text, "Section_desc")
            rels.append(SimpleRel(section, desc, "HAS_DESC"))

    # Section -> Group
    if group and section:
        rels.append(SimpleRel(section, group, "SECTION"))

    return [SimpleGraphDocument(nodes, rels)]



# 6) Mapping and upsert helpers
def sanitize_label(label: str) -> str:
    label = label or "Entity"
    label = re.sub(r"[^A-Za-z0-9_]", "_", label)
    if not label:
        label = "Entity"
    if label[0].isdigit():
        label = f"_{label}"
    return label


def sanitize_rel_type(rtype: str) -> str:
    rtype = (rtype or "RELATES_TO").upper()
    rtype = re.sub(r"[^A-Z0-9_]", "_", rtype)
    if not rtype:
        rtype = "RELATES_TO"
    if rtype[0].isdigit():
        rtype = f"R_{rtype}"
    return rtype


def map_node(node: SimpleNode):
    name = (node.id or "").strip()
    raw = (node.type or "Entity").strip() or "Entity"

    label = raw
    props = {"name": name, "original_type": raw}

    # Normalize known legal terms
    if name in {"โจทก", "โจทก์"}:
        label = "Person"
        props["_role_hint"] = "Plaintiff"
    elif name == "จำเลย":
        label = "Person"
        props["_role_hint"] = "Defendant"

    if label not in ALLOWED_NODE_LABELS:
        label = "Entity"
    return sanitize_label(label), props


def setup_constraints():
    stmts = [
        "CREATE CONSTRAINT uniq_person_name IF NOT EXISTS FOR (n:Person) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_legalrole_value IF NOT EXISTS FOR (n:LegalRole) REQUIRE n.value IS UNIQUE",
        "CREATE CONSTRAINT uniq_courtcase_caseid IF NOT EXISTS FOR (n:CourtCase) REQUIRE n.caseId IS UNIQUE",
        "CREATE CONSTRAINT uniq_group_name IF NOT EXISTS FOR (n:Group) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_section_name IF NOT EXISTS FOR (n:Section) REQUIRE n.name IS UNIQUE",
    ]
    

    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            for q in stmts:
                try:
                    session.run(q)
                except Exception as e:
                    print(f"Constraint warn: {e}")


def upsert_graph(graph_docs: List[SimpleGraphDocument], case_id: str):
    nodes = {}
    rels = []
    roles = []  # (person_name, role_value)

    for gd in graph_docs:
        for n in gd.nodes:
            label, props = map_node(n)
            key = (label, props["name"])
            if key not in nodes:
                nodes[key] = props
            else:
                nodes[key].update({k: v for k, v in props.items() if v})
            if label == "Person" and props.get("_role_hint"):
                roles.append((props["name"], props["_role_hint"]))

        for r in gd.relationships:
            s_label, s_props = map_node(r.source)
            t_label, t_props = map_node(r.target)
            r_type = sanitize_rel_type(r.type)
            rels.append((s_label, s_props["name"], r_type, t_label, t_props["name"]))

    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            # Ensure the case node exists
            session.run(
                "MERGE (c:CourtCase {caseId: $cid}) SET c.name = coalesce(c.name, $cid)",
                cid=case_id,
            )

            # Upsert nodes
            for (label, name), props in nodes.items():
                props = {k: v for k, v in props.items() if not k.startswith("_")}
                q = f"MERGE (n:`{label}` {{name: $name}}) SET n += $props"
                try:
                    session.run(q, name=name, props=props)
                except Exception as e:
                    print(f"Node upsert warn [{label}:{name}]: {e}")

            # Upsert relationships
            for s_label, s_name, r_type, t_label, t_name in rels:
                q = (
                    f"MATCH (a:`{s_label}` {{name: $sname}}), (b:`{t_label}` {{name: $tname}}) "
                    f"MERGE (a)-[:`{r_type}`]->(b)"
                )
                try:
                    session.run(q, sname=s_name, tname=t_name)
                except Exception as e:
                    print(f"Rel upsert warn [{s_label}:{s_name} -{r_type}-> {t_label}:{t_name}]: {e}")

            # Create LegalRole nodes + HAS_ROLE edges
            for person_name, role_value in roles:
                try:
                    session.run("MERGE (r:LegalRole {value: $v, name: $v})", v=role_value)
                    session.run(
                        "MATCH (p:Person {name: $p}), (r:LegalRole {value: $v}) MERGE (p)-[:HAS_ROLE]->(r)",
                        p=person_name,
                        v=role_value,
                    )
                except Exception as e:
                    print(f"HAS_ROLE warn [{person_name}->{role_value}]: {e}")

            # Link parties to the case; plaintiffs also CLAIM the case
            for person_name, role_value in roles:
                try:
                    session.run(
                        "MATCH (p:Person {name: $p}), (c:CourtCase {caseId: $cid}) MERGE (p)-[:PARTY]->(c)",
                        p=person_name,
                        cid=case_id,
                    )
                    if role_value == "Plaintiff":
                        session.run(
                            "MATCH (p:Person {name: $p}), (c:CourtCase {caseId: $cid}) MERGE (p)-[:CLAIMS]->(c)",
                            p=person_name,
                            cid=case_id,
                        )
                except Exception as e:
                    print(f"Case link warn [{person_name}]: {e}")

            # Link the case to observed MoneyAmount and Date nodes (case-scoped facts)
            try:
                money_names = [props["name"] for (label, _name), props in nodes.items() if label == "MoneyAmount"]
                for mname in set(money_names):
                    session.run(
                        "MATCH (c:CourtCase {caseId: $cid}) MERGE (m:MoneyAmount {name: $m}) MERGE (c)-[:HAS_AMOUNT]->(m)",
                        cid=case_id,
                        m=mname,
                    )
                date_names = [props["name"] for (label, _name), props in nodes.items() if label == "Date"]
                for dname in set(date_names):
                    session.run(
                        "MATCH (c:CourtCase {caseId: $cid}) MERGE (d:Date {name: $d}) MERGE (c)-[:OCCURRED_ON]->(d)",
                        cid=case_id,
                        d=dname,
                    )
            except Exception as e:
                print(f"Case link amounts/dates warn: {e}")


# 7) Case ID detection (lightweight)
def detect_case_id(texts: List[str]) -> str:
    pats = [
        r"คดีหมายเลข[ดำแดง]?\s*(ที่)?\s*([0-9/\-]+)",
        r"หมายเลขคดี\s*([0-9/\-]+)",
        r"คดี.*?([0-9]+/[0-9]+)",
    ]
    for t in texts:
        for p in pats:
            m = re.search(p, t)
            if m:
                num = m.group(m.lastindex) if m.lastindex else m.group(0)
                return f"CASE-{num}".replace(" ", "")
    h = hashlib.sha1("\n".join(texts).encode("utf-8")).hexdigest()[:10]
    return f"CASE-{h}"


# 9) Doc chunk indexing (Vector store metadata in Neo4j)
def index_doc_chunks(text_chunks: List[str], case_id: str):
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            for i, text in enumerate(text_chunks, 1):
                sec = ""
                m_sec = re.search(r"มาตรา\s*(\d+)", text)
                if m_sec:
                    sec = f"มาตรา {m_sec.group(1)}"
                else:
                    m_grp = re.search(r"หมวด\s*(\d+)", text)
                    if m_grp:
                        sec = f"หมวด {m_grp.group(1)}"

                session.run(
                    "MERGE (d:DocChunk {caseId: $cid, chunkId: $id}) "
                    "SET d.text = $text, d.page = $page, d.section = $section",
                    cid=case_id,
                    id=f"{case_id}-{i}",
                    text=text,
                    page=i,
                    section=sec,   # <- สตริงเสมอ (อย่างน้อย "")
                )


def fetch_doc_chunks(case_id: Optional[str] = None) -> List[dict]:
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            if case_id:
                q = (
                    "MATCH (d:DocChunk {caseId: $cid}) "
                    "RETURN d.caseId AS caseId, d.chunkId AS chunkId, d.text AS text, "
                    "d.page AS page, coalesce(d.section, '') AS section "
                    "ORDER BY d.page ASC"
                )
                res = session.run(q, cid=case_id)
            else:
                q = (
                    "MATCH (d:DocChunk) "
                    "RETURN d.caseId AS caseId, d.chunkId AS chunkId, d.text AS text, "
                    "d.page AS page, coalesce(d.section, '') AS section "
                    "ORDER BY d.caseId, d.page ASC"
                )
                res = session.run(q)
            return [r.data() for r in res]


# 10) Tiny TF-IDF (no dependencies) + cosine
def tokenize(s: str) -> List[str]:
    if not s:
        return []
    # แยกง่ายๆ ด้วยช่องว่าง/อักขระไม่ใช่ตัวอักษร (Thai จะหยาบแต่พอเดโมได้)
    toks = re.split(r"\s+|[^\w\u0E00-\u0E7F]+", s.lower())
    return [t for t in toks if t]


def build_tfidf(texts: List[str], max_vocab: int = 2048):
    # DF
    df = {}
    docs_tokens = []
    for t in texts:
        toks = tokenize(t)
        docs_tokens.append(toks)
        for w in set(toks):
            df[w] = df.get(w, 0) + 1
    N = max(1, len(texts))
    # เลือก vocab ที่พบบ่อยสุด (ลดมิติ)
    vocab_terms = sorted(df.items(), key=lambda x: (-x[1], x[0]))[:max_vocab]
    vocab = {w: i for i, (w, _) in enumerate(vocab_terms)}
    # IDF
    idf = [0.0] * len(vocab)
    for w, idx in vocab.items():
        idf[idx] = math.log((N + 1) / (df[w] + 1)) + 1.0
    # สร้างเวกเตอร์เอกสาร
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


def vectorize_query(q: str, vocab: dict, idf: List[float]):
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


# 11) Graph retrieval (facts) + Hybrid search
def graph_retrieve(case_id: Optional[str] = None, limit: int = 20) -> List[dict]:
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            if case_id:
                q = """
                MATCH (c:CourtCase {caseId: $cid})
                OPTIONAL MATCH (p:Person)-[:PARTY]->(c)
                OPTIONAL MATCH (p)-[:HAS_ROLE]->(role:LegalRole)
                OPTIONAL MATCH (c)-[:OCCURRED_ON]->(d:Date)
                OPTIONAL MATCH (c)-[:HAS_AMOUNT]->(m:MoneyAmount)
                OPTIONAL MATCH (sec:Section)-[:HAS_DESC]->(desc:Section_desc)
                RETURN DISTINCT 
                    p.name AS person, role.value AS role, c.caseId AS caseId,
                    d.name AS date, m.name AS amount,
                    sec.name AS section, desc.name AS section_desc
                LIMIT $limit
                """
                res = session.run(q, cid=case_id, limit=limit)
            else:
                q = """
                MATCH (c:CourtCase)
                OPTIONAL MATCH (p:Person)-[:PARTY]->(c)
                OPTIONAL MATCH (p)-[:HAS_ROLE]->(role:LegalRole)
                OPTIONAL MATCH (c)-[:OCCURRED_ON]->(d:Date)
                OPTIONAL MATCH (c)-[:HAS_AMOUNT]->(m:MoneyAmount)
                OPTIONAL MATCH (sec:Section)-[:HAS_DESC]->(desc:Section_desc)
                RETURN DISTINCT 
                    p.name AS person, role.value AS role, c.caseId AS caseId,
                    d.name AS date, m.name AS amount,
                    sec.name AS section, desc.name AS section_desc
                LIMIT $limit
                """
                res = session.run(q, limit=limit)
            return [r.data() for r in res]

THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

def normalize_thai_digits(text: str) -> str:
    return text.translate(THAI_DIGITS)
    
def tokenize(s: str) -> List[str]:
    if not s:
        return []
    s = normalize_thai_digits(s.lower())
    toks = re.split(r"\s+|[^\w\u0E00-\u0E7F]+", s)
    return [t for t in toks if t]


def hybrid_search(query: str, case_id: Optional[str] = None, k: int = 5):
    docs = fetch_doc_chunks(case_id)
    if not docs:
        return [], []

    texts = [d["text"] for d in docs]
    vocab, idf, doc_vecs = build_tfidf(texts)
    qv = vectorize_query(query, vocab, idf)

    scored = []
    for i, dv in enumerate(doc_vecs):
        score = cosine(qv, dv)
        if score > 0:
            item = dict(docs[i])
            item["score"] = score
            scored.append(item)
    scored.sort(key=lambda x: -x["score"])
    top_docs = scored[:k]

    facts = graph_retrieve(case_id=case_id, limit=20)
    return top_docs, facts


# 12) Answer synthesis with citations (deterministic fallback)
def synthesize_answer(query: str, doc_hits: List[dict], facts: List[dict], case_id: Optional[str] = None) -> str:
    lines = []
    # สรุปจากกราฟ
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

    # สรุปจากเอกสาร (เลือกประโยคที่คล้ายสุด)
    if doc_hits:
        lines.append("สาระจากเอกสารที่ใกล้เคียง:")
        for d in doc_hits:
            preview = d["text"].strip().replace("\n", " ")
            if len(preview) > 180:
                preview = preview[:180] + "..."
            lines.append(f"- {preview}")

    # อ้างอิงหน้า/คดี
    if doc_hits:
        lines.append("อ้างอิง:")
        for d in doc_hits:
            cid = d.get("caseId") or case_id or "-"
            page = d.get("page") or "-"
            lines.append(f"- [Case: {cid}, page: {page}] {d.get('chunkId', '')}")

    if not lines:
        lines.append("ไม่พบข้อมูลที่เกี่ยวข้องเพียงพอสำหรับคำถามนี้")

    return "\n".join(lines)


# FastAPI app (Swagger at /docs)
app = FastAPI(
    title="Neo Legal KG API",
    description="Thai legal KG with rule-based extraction and hybrid search",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class IngestRequest(BaseModel):
    texts: List[str] = Field(
        ..., description="ข้อความคดีเป็นลิสต์ของชิ้นข้อความ",
        example=[
            "เมื่อวันที่ 1 พฤศจิกายน 2557 จำเลยได้จ้างโจทก์เข้าทำงานเป็นลูกจ้างในตำแหน่ง แม่บ้านได้รับค่าจ้างเป็นรายเดือนอัตราค่าจ้างสุดท้ายเดือนละ 10,000 บาทกำหนดจ่ายค่าจ้างทุกวันสิ้นเดือน"
        ],
    )
    case_id: Optional[str] = Field(
        None,
        description="ถ้าไม่ส่งหรือเป็น 'string' ระบบจะตรวจจับ/สร้างอัตโนมัติ",
        example=None,
    )


class AskRequest(BaseModel):
    question: str
    case_id: Optional[str] = None
    k: int = 5


INGEST_BUFFER = deque()
MAX_BUFFER_BEFORE_CLEAR = 4

def latest_case_id() -> Optional[str]:
    try:
        return INGEST_BUFFER[-1]["case_id"]
    except Exception:
        return None



@app.post("/ingest")
def ingest(req: IngestRequest):
    if not req.texts:
        raise HTTPException(status_code=400, detail="texts is required")
    setup_constraints()
    provided = (req.case_id or "").strip()
    if not provided or provided.lower() in {"string", "auto", "null"}:
        case_id = detect_case_id(req.texts)
    else:
        case_id = provided
    all_docs: List[SimpleGraphDocument] = []
    for chunk in req.texts:
        docs = rule_based_extract(chunk)
        all_docs.extend(docs)
    upsert_graph(all_docs, case_id)
    index_doc_chunks(req.texts, case_id)
    INGEST_BUFFER.append({"texts": req.texts, "case_id": case_id})
    return {"case_id": case_id, "chunks": len(req.texts)}


@app.get("/cases/{case_id}/facts")
def get_facts(case_id: str, limit: int = 20):
    facts = graph_retrieve(case_id=case_id, limit=limit)
    return {"case_id": case_id, "facts": facts}

@app.get("/Health")
def health_check():
    return {"status": "ok"}

@app.get("/chunks/{case_id}")
def get_chunks(case_id: str):
    items = fetch_doc_chunks(case_id)
    return {"case_id": case_id, "chunks": items}


@app.get("/search")
def search(q: str = Query(..., min_length=1), case_id: Optional[str] = None, k: int = 5):
    case_id = case_id or latest_case_id()
    docs, facts = hybrid_search(q, case_id=case_id, k=k)
    return {"query": q, "case_id": case_id, "top_docs": docs, "facts": facts}


@app.get("/answer")
def answer(q: str = Query(..., min_length=1), case_id: Optional[str] = None, k: int = 5):
    case_id = case_id or latest_case_id()
    doc_hits, facts = hybrid_search(q, case_id=case_id, k=k)
    ans = synthesize_answer(q, doc_hits, facts, case_id=case_id)
    INGEST_BUFFER.clear()
    return {"query": q, "case_id": case_id, "answer": ans, "doc_hits": doc_hits, "facts": facts}


@app.post("/ask")
def ask(req: AskRequest):
    q = (req.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="question is required")
    cid = req.case_id or latest_case_id()
    doc_hits, facts = hybrid_search(q, case_id=cid, k=req.k)
    ans = synthesize_answer(q, doc_hits, facts, case_id=cid)
    return {"query": q, "case_id": cid, "answer": ans, "doc_hits": doc_hits, "facts": facts}


# 8) Main: minimal pipeline (schema -> extract -> upsert)
def main():
    print("[KG] Minimal legal ontology pipeline (no vectors)")

    # Example input chunks (Thai labor case)
    text_chunks = [
     "หมวด 15 การส่งหนังสือ มาตรา 143 ในการส่งคำสั่งหรือหนังสือของอธิบดีหรือพนักงานตรวจแรงงานซึ่งสั่งการตามพระราชบัญญัตินี้ ให้ส่งทางไปรษณีย์ลงทะเบียนตอบรับหรือพนักงานตรวจแรงงานจะนำไปส่งเองหรือให้เจ้าหน้าที่นำไปส่ง ณ ภูมิลำเนาหรือถิ่นที่อยู่หรือสำนักงานของนายจ้างในเวลาทำการของนายจ้าง ถ้าไม่พบนายจ้าง ณ ภูมิลำเนาหรือถิ่นที่อยู่ หรือสำนักงานของนายจ้าง หรือพบนายจ้างแต่นายจ้างปฏิเสธไม่ยอมรับ จะส่งให้แก่บุคคลใดซึ่งบรรลุนิติภาวะแล้วและอยู่หรือทำงานในบ้านหรือสำนักงานที่ปรากฏว่าเป็นของนายจ้างนั้นก็ได้ เมื่อได้ดำเนินการดังกล่าวแล้ว ให้ถือว่านายจ้างได้รับคำสั่งหรือหนังสือของอธิบดีหรือพนักงานตรวจแรงงานนั้นแล้ว ถ้าการส่งตามวรรคหนึ่งไม่สามารถกระทำได้ ให้ส่งโดยปิดคำสั่งหรือหนังสือของอธิบดีหรือพนักงานตรวจแรงงานในที่ซึ่งเห็นได้ง่าย ณ สำนักงานของนายจ้าง สถานที่ทำงานของลูกจ้าง ภูมิลำเนาหรือถิ่นที่อยู่ของนายจ้าง เมื่อได้ดำเนินการดังกล่าวและเวลาได้ล่วงพ้นไปไม่น้อยกว่าสิบห้าวันแล้ว ให้ถือว่านายจ้างได้รับคำสั่งหรือหนังสือของอธิบดีหรือพนักงานตรวจแรงงานนั้นแล้ว",

"หมวด 16 บทกำหนดโทษ มาตรา 144 นายจ้างผู้ใดฝ่าฝืนหรือไม่ปฏิบัติตามบทบัญญัติดังต่อไปนี้ ต้องระวางโทษจำคุกไม่เกินหกเดือน หรือปรับไม่เกินหนึ่งแสนบาท หรือทั้งจำทั้งปรับ (1) มาตรา 10 มาตรา 17/1 มาตรา 23 วรรคสอง มาตรา 24 มาตรา 25 มาตรา 26 มาตรา 37 มาตรา 38 มาตรา 39 มาตรา 39/1 มาตรา 40 มาตรา 42 มาตรา 43 มาตรา 46 มาตรา 47 มาตรา 48 มาตรา 51 มาตรา 57/1 มาตรา 61 มาตรา 62 มาตรา 63 มาตรา 64 มาตรา 67 มาตรา 70 มาตรา 71 มาตรา 72 มาตรา 76 มาตรา 90 วรรคหนึ่ง มาตรา 118 วรรคหนึ่ง หรือมาตรา 118/1 วรรคสอง (2) มาตรา 120 มาตรา 120/1 มาตรา 121 หรือมาตรา 122 ในส่วนที่เกี่ยวกับการไม่จ่ายค่าชดเชยพิเศษแทนการบอกกล่าวล่วงหน้าหรือค่าชดเชยพิเศษ (3) กฎกระทรวงที่ออกมาตามมาตรา 22 ในส่วนที่เกี่ยวกับการคุ้มครองแรงงานในกรณีต่าง ๆ ที่ไม่เกี่ยวกับการจ้างเด็กอายุต่ำกว่าที่กำหนดในกฎกระทรวงเป็นลูกจ้างหรือการรับเด็กซึ่งมีอายุต่ำกว่าที่กำหนดในกฎกระทรวงเข้าทำงาน หรือการห้ามมิให้นายจ้างให้ลูกจ้างซึ่งเป็นเด็กอายุต่ำกว่าสิบแปดปีทำงานตามประเภทของงานและสถานที่ที่กำหนดในกฎกระทรวง หรือกฎกระทรวงที่ออกตามมาตรา 95 ในกรณีที่นายจ้างฝ่าฝืนหรือไม่ปฏิบัติตามมาตรา 37 มาตรา 38 มาตรา 39 มาตรา 39/1 มาตรา 42 มาตรา 47 หรือมาตรา 48 เป็นเหตุให้ลูกจ้างได้รับอันตรายแก่กายหรือจิตใจ หรือถึงแก่ความตาย ต้องระวางโทษจำคุกไม่เกินหนึ่งปี หรือปรับไม่เกินสองแสนบาท หรือทั้งจำทั้งปรับ",

"หมวด 16 บทกำหนดโทษ มาตรา 144/1 ผู้ประกอบกิจการผู้ใดไม่ปฏิบัติตามมาตรา 11/1 ต้องระวางโทษปรับไม่เกินหนึ่งแสนบาท",

"หมวด 16 บทกำหนดโทษ มาตรา 145 นายจ้างผู้ใดไม่ปฏิบัติตามมาตรา 23 วรรคหนึ่งหรือวรรคสาม ต้องระวางโทษปรับไม่เกินห้าพันบาท",

"หมวด 16 บทกำหนดโทษ มาตรา 146 นายจ้างผู้ใดไม่ปฏิบัติตามมาตรา 15 มาตรา 27 มาตรา 28 มาตรา 29 มาตรา 30 วรรคหนึ่ง มาตรา 45 มาตรา 53 มาตรา 54 มาตรา 56 มาตรา 57 มาตรา 58 มาตรา 59 มาตรา 65 มาตรา 66 มาตรา 73 มาตรา 74 มาตรา 75 วรรคหนึ่ง มาตรา 77 มาตรา 99 มาตรา 108 มาตรา 111 มาตรา 112 มาตรา 113 มาตรา 114 มาตรา 115 มาตรา 117 หรือไม่บอกกล่าวล่วงหน้าตามมาตรา 121 วรรคหนึ่ง หรือมาตรา 139 (2) หรือ (3) ต้องระวางโทษปรับไม่เกินสองหมื่นบาท",

"หมวด 16 บทกำหนดโทษ มาตรา 147 ผู้ใดฝ่าฝืนมาตรา 16 ต้องระวางโทษปรับไม่เกินสองหมื่นบาท",

"หมวด 16 บทกำหนดโทษ มาตรา 148 นายจ้างผู้ใดฝ่าฝืนมาตรา 31 ต้องระวางโทษจำคุกไม่เกินหนึ่งปี หรือปรับไม่เกินสองแสนบาท หรือทั้งจำทั้งปรับ",

"หมวด 16 บทกำหนดโทษ มาตรา 148/1 นายจ้างผู้ใดฝ่าฝืนมาตรา 44 หรือกฎกระทรวงที่ออกตามมาตรา 22 ในส่วนที่เกี่ยวกับการจ้างเด็กอายุต่ำกว่าที่กำหนดในกฎกระทรวงเป็นลูกจ้างหรือการรับเด็กซึ่งมีอายุต่ำกว่าที่กำหนดในกฎกระทรวงเข้าทำงาน ต้องระวางโทษปรับตั้งแต่สี่แสนบาทถึงแปดแสนบาทต่อลูกจ้างหนึ่งคน หรือจำคุกไม่เกินสองปี หรือทั้งปรับทั้งจำ",

"หมวด 16 บทกำหนดโทษ มาตรา 148/2 นายจ้างผู้ใดฝ่าฝืนมาตรา 49 หรือมาตรา 50 หรือกฎกระทรวงที่ออกตามมาตรา 22 ในส่วนที่เกี่ยวกับการห้ามมิให้นายจ้างให้ลูกจ้างซึ่งเป็นเด็กอายุต่ำกว่าสิบแปดปีทำงานตามประเภทของงานและสถานที่ที่กำหนด ต้องระวางโทษปรับตั้งแต่สี่แสนบาทถึงแปดแสนบาทต่อลูกจ้างหนึ่งคน หรือจำคุกไม่เกินสองปี หรือทั้งปรับทั้งจำ ถ้าการกระทำความผิดตามวรรคหนึ่งเป็นเหตุให้ลูกจ้างได้รับอันตรายแก่กายหรือจิตใจหรือถึงแก่ความตาย ต้องระวางโทษปรับตั้งแต่แปดแสนบาทถึงสองล้านบาทต่อลูกจ้างหนึ่งคน หรือจำคุกไม่เกินสี่ปี หรือทั้งปรับทั้งจำ",

"หมวด 16 บทกำหนดโทษ มาตรา 149 นายจ้างผู้ใดไม่ปฏิบัติตามมาตรา 52 มาตรา 55 มาตรา 75 วรรคสอง มาตรา 90 วรรคสอง มาตรา 110 หรือมาตรา 116 ต้องระวางโทษปรับไม่เกินหนึ่งหมื่นบาท",

"หมวด 16 บทกำหนดโทษ มาตรา 150 ผู้ใดไม่อำนวยความสะดวก ไม่มาให้ถ้อยคำ ไม่ส่งเอกสารหรือวัตถุใด ๆ ตามหนังสือเรียกของคณะกรรมการค่าจ้าง คณะกรรมการสวัสดิการแรงงาน คณะอนุกรรมการของคณะกรรมการดังกล่าว หรือผู้ซึ่งคณะกรรมการหรือคณะอนุกรรมการเช่นว่านั้นมอบหมาย แล้วแต่กรณี หรือไม่อำนวยความสะดวกแก่พนักงานตรวจแรงงาน หรือแพทย์ นักสังคมสงเคราะห์ หรือผู้เชี่ยวชาญตามมาตรา 142 ต้องระวางโทษจำคุกไม่เกินหนึ่งเดือน หรือปรับไม่เกินสองพันบาท หรือทั้งจำทั้งปรับ",

"หมวด 16 บทกำหนดโทษ มาตรา 151 ผู้ใดขัดขวางการปฏิบัติหน้าที่ของคณะกรรมการค่าจ้าง คณะกรรมการสวัสดิการแรงงาน คณะอนุกรรมการของคณะกรรมการดังกล่าว หรือผู้ซึ่งคณะกรรมการหรือคณะอนุกรรมการเช่นว่านั้นมอบหมาย แล้วแต่กรณี หรือขัดขวางการปฏิบัติหน้าที่ของพนักงานตรวจแรงงาน หรือแพทย์ นักสังคมสงเคราะห์ หรือผู้เชี่ยวชาญตามมาตรา 142 ต้องระวางโทษจำคุกไม่เกินหนึ่งปี หรือปรับไม่เกินสองหมื่นบาท หรือทั้งจำทั้งปรับ ผู้ใดไม่ปฏิบัติตามคำสั่งของพนักงานตรวจแรงงานที่สั่งตามมาตรา 124 ต้องระวางโทษจำคุกไม่เกินหนึ่งปี หรือปรับไม่เกินสองหมื่นบาท หรือทั้งจำทั้งปรับ",

"หมวด 16 บทกำหนดโทษ มาตรา 152 นายจ้างผู้ใดไม่ปฏิบัติตามมาตรา 96 ต้องระวางโทษปรับไม่เกินห้าหมื่นบาท",

"หมวด 16 บทกำหนดโทษ มาตรา 153 นายจ้างผู้ใดไม่ปฏิบัติตามมาตรา 98 ต้องระวางโทษจำคุกไม่เกินหนึ่งเดือน หรือปรับไม่เกินสองพันบาท หรือทั้งจำทั้งปรับ",

"หมวด 16 บทกำหนดโทษ มาตรา 154 (ยกเลิก)",

"หมวด 16 บทกำหนดโทษ มาตรา 155 (ยกเลิก)",

"หมวด 16 บทกำหนดโทษ มาตรา 155/1 นายจ้างผู้ใดไม่ยื่นหรือไม่แจ้งแบบแสดงสภาพการจ้างและสภาพการทำงานตามมาตรา 115/1 ต้องระวางโทษปรับไม่เกินสองหมื่นบาท",

"หมวด 16 บทกำหนดโทษ มาตรา 156 นายจ้างผู้ใดไม่ยื่นแบบรายการหรือไม่แจ้งเป็นหนังสือขอเปลี่ยนแปลงหรือแก้ไขเพิ่มเติมรายการภายในกำหนดเวลาตามมาตรา 130 หรือยื่นแบบรายการ หรือแจ้งเป็นหนังสือขอเปลี่ยนแปลงหรือแก้ไขเพิ่มเติมรายการตามมาตรา 130 โดยกรอกข้อความอันเป็นเท็จ ต้องระวางโทษจำคุกไม่เกินหกเดือน หรือปรับไม่เกินหนึ่งหมื่นบาท หรือทั้งจำทั้งปรับ",

"หมวด 16 บทกำหนดโทษ มาตรา 157 พนักงานเจ้าหน้าที่ผู้ใดเปิดเผยข้อเท็จจริงใดเกี่ยวกับกิจการของนายจ้างอันเป็นข้อเท็จจริงตามที่ปกติวิสัยของนายจ้างจะพึงสงวนไว้ไม่เปิดเผยซึ่งตนได้มาหรือล่วงรู้เนื่องจากการปฏิบัติการตามพระราชบัญญัตินี้ ต้องระวางโทษจำคุกไม่เกินหนึ่งเดือน หรือปรับไม่เกินสองพันบาท หรือทั้งจำทั้งปรับ เว้นแต่เป็นการเปิดเผยในการปฏิบัติราชการเพื่อประโยชน์แห่งพระราชบัญญัตินี้ หรือเพื่อประโยชน์แก่การคุ้มครองแรงงาน การแรงงานสัมพันธ์ หรือการสอบสวน หรือการพิจารณาคดี",

"หมวด 16 บทกำหนดโทษ มาตรา 158 ในกรณีที่ผู้กระทำความผิดเป็นนิติบุคคล ถ้าการกระทำความผิดของนิติบุคคลนั้นเกิดจากการสั่งการ หรือการกระทำของบุคคลใด หรือไม่สั่งการ หรือไม่กระทำการอันเป็นหน้าที่ที่ต้องกระทำของกรรมการผู้จัดการ หรือบุคคลใดซึ่งรับผิดชอบในการดำเนินงานของนิติบุคคลนั้น ผู้นั้นต้องรับโทษตามที่บัญญัติไว้สำหรับความผิดนั้น ๆ ด้วย",

"หมวด 16 บทกำหนดโทษ มาตรา 159 บรรดาความผิดตามพระราชบัญญัตินี้ เว้นแต่ความผิดตามมาตรา 157 ถ้าเจ้าพนักงานดังต่อไปนี้ เห็นว่าผู้กระทำผิดไม่ควรได้รับโทษจำคุกหรือไม่ควรถูกฟ้องร้อง ให้มีอำนาจเปรียบเทียบดังนี้ (1) อธิบดีหรือผู้ซึ่งอธิบดีมอบหมาย สำหรับความผิดที่เกิดขึ้นในกรุงเทพมหานคร (2) ผู้ว่าราชการจังหวัดหรือผู้ซึ่งผู้ว่าราชการจังหวัดมอบหมาย สำหรับความผิดที่เกิดขึ้นในจังหวัดอื่น ในกรณีที่มีการสอบสวน ถ้าพนักงานสอบสวนพบว่าบุคคลใดกระทำความผิดตามพระราชบัญญัตินี้ และบุคคลนั้นยินยอมให้เปรียบเทียบ ให้พนักงานสอบสวนส่งเรื่องให้อธิบดี หรือผู้ว่าราชการจังหวัด แล้วแต่กรณี ภายในเจ็ดวันนับแต่วันที่บุคคลนั้นแสดงความยินยอมให้เปรียบเทียบ เมื่อผู้กระทำผิดได้ชำระเงินค่าปรับตามจำนวนที่เปรียบเทียบภายในสามสิบวันแล้ว ให้ถือว่าคดีเลิกกันตามประมวลกฎหมายวิธีพิจารณาความอาญา ถ้าผู้กระทำผิดไม่ยินยอมให้เปรียบเทียบ หรือเมื่อยินยอมแล้วไม่ชำระเงินค่าปรับภายในกำหนดเวลาตามวรรคสาม ให้ดำเนินคดีต่อไป"

    ]


    # Setup DB constraints and case
    setup_constraints()
    case_id = detect_case_id(text_chunks)
    print(f"Case ID: {case_id}")

    # Extract and collect graph docs
    all_docs: List[SimpleGraphDocument] = []
    for i, chunk in enumerate(text_chunks, 1):
        print(f"- Extracting chunk {i}")
        docs = rule_based_extract(chunk)
        all_docs.extend(docs)

    # Upsert to Neo4j (graph)
    print("- Upserting graph to Neo4j")
    upsert_graph(all_docs, case_id)

    # Index doc chunks (vector store metadata)
    print("- Indexing document chunks")
    index_doc_chunks(text_chunks, case_id)

    # Hybrid search demo
    query = "มาตรา 145 มีอะไรบ้าง "
    print(f"- Hybrid search: {query}")
    doc_hits, facts = hybrid_search(query, case_id=case_id, k=2)

    # Synthesize answer with citations
    answer = synthesize_answer(query, doc_hits, facts, case_id=case_id)
    print("\n[Answer]")
    print(answer)

    print("Done. Query your KG in Neo4j.")


if __name__ == "__main__":
    main()

