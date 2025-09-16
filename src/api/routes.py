"""FastAPI route handlers"""

from collections import deque
from typing import Optional, List, Dict
from fastapi import APIRouter, HTTPException, Query, Request
from ..models.api import (
    IngestRequest, 
    AskRequest,
    IngestResponse,
    FactResponse,
    ChunkResponse,
    SearchResponse,
    AnswerResponse
)
from ..services.neo4j_service import (
    setup_constraints, 
    upsert_graph, 
    index_doc_chunks,
    fetch_doc_chunks,
    graph_retrieve
)
from ..services.extraction import rule_based_extract, detect_case_id
from ..utils.thai_parser import parse_person_address, llm_normalize_plaintiff
from ..models.graph import SimpleNode, SimpleRel
from ..services.search import hybrid_search, synthesize_answer
from ..models.graph import SimpleGraphDocument


# Router instance
router = APIRouter()

# Ingest buffer for tracking recent case IDs
INGEST_BUFFER = deque(maxlen=10)


def latest_case_id() -> Optional[str]:
    """Get the most recent case ID from buffer"""
    try:
        return INGEST_BUFFER[-1]["case_id"]
    except (IndexError, KeyError):
        return None


@router.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest):
    """Ingest text documents and extract knowledge graph"""
    if not req.texts:
        raise HTTPException(status_code=400, detail="texts is required")
    
    setup_constraints()
    
    # Determine case ID
    provided = (req.case_id or "").strip()
    if not provided or provided.lower() in {"string", "auto", "null"}:
        case_id = detect_case_id(req.texts)
    else:
        case_id = provided
    
    # Extract graph from all chunks
    all_docs: list[SimpleGraphDocument] = []
    for chunk in req.texts:
        docs = rule_based_extract(chunk)
        all_docs.extend(docs)
    
    # Upsert to Neo4j
    upsert_graph(all_docs, case_id)
    index_doc_chunks(req.texts, case_id)
    
    # Track in buffer
    INGEST_BUFFER.append({"texts": req.texts, "case_id": case_id})
    
    return {"case_id": case_id, "chunks": len(req.texts)}


@router.get("/cases/{case_id}/facts", response_model=FactResponse)
def get_facts(case_id: str, limit: int = 20):
    """Get graph facts for a specific case"""
    facts = graph_retrieve(case_id=case_id, limit=limit)
    return {"case_id": case_id, "facts": facts}


@router.get("/Health")
def health_check():
    """Health check endpoint"""
    return {"status": "ok"}


@router.get("/chunks/{case_id}", response_model=ChunkResponse)
def get_chunks(case_id: str):
    """Get document chunks for a specific case"""
    items = fetch_doc_chunks(case_id)
    return {"case_id": case_id, "chunks": items}


@router.get("/search", response_model=SearchResponse)
def search(q: str = Query(..., min_length=1), case_id: Optional[str] = None, k: int = 5):
    """Search documents and graph"""
    case_id = case_id or latest_case_id()
    docs, facts = hybrid_search(q, case_id=case_id, k=k)
    
    return {"query": q, "case_id": case_id, "top_docs": docs, "facts": facts}


@router.get("/answer", response_model=AnswerResponse)
def answer(q: str = Query(..., min_length=1), case_id: Optional[str] = None, k: int = 5):
    """Answer questions using hybrid search"""
    case_id = case_id or latest_case_id()
    doc_hits, facts = hybrid_search(q, case_id=case_id, k=k)
    ans = synthesize_answer(q, doc_hits, facts, case_id=case_id)
    
    # Clear buffer after answering
    INGEST_BUFFER.clear()
    
    return {"query": q, "case_id": case_id, "answer": ans, "doc_hits": doc_hits, "facts": facts}


@router.post("/ask", response_model=AnswerResponse)
def ask(req: AskRequest):
    """Answer questions (POST version)"""
    q = (req.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="question is required")
    
    cid = req.case_id or latest_case_id()
    doc_hits, facts = hybrid_search(q, case_id=cid, k=req.k)
    ans = synthesize_answer(q, doc_hits, facts, case_id=cid)
    
    return {"query": q, "case_id": cid, "answer": ans, "doc_hits": doc_hits, "facts": facts}

# เพิ่มข้อมูลเอกสารศาลแรงงาน
COURT_DOCUMENTS = [
    {
        "id": 1,
        "title": "คำฟ้องคดีแรงงาน รง1",
        "description": "คำฟ้องคดีแรงงาน เลิกจ้างไม่เป็นธรรม",
        "keywords": ["คดีแรงงาน", "เลิกจ้าง", "ไม่เป็นธรรม", "คำฟ้อง", "รง1"],
        "court": "ศาลแรงงานกลาง"
    },
    {
        "id": 2,
        "title": "คำร้องคดีแรงงาน รง1",
        "description": "คำร้องขอค่าชดเชยการเลิกจ้าง",
        "keywords": ["ค่าชดเชย", "เลิกจ้าง", "คำร้อง", "รง2"],
        "court": "ศาลแรงงานกลาง"
    },
    {
        "id": 3,
        "title": "คำฟ้องคดีค่าจ้างค้างจ่าย รง1",
        "description": "คำฟ้องเรียกร้องค่าจ้างและค่าล่วงเวลา",
        "keywords": ["ค่าจ้าง", "ค้างจ่าย", "ค่าล่วงเวลา", "รง3"],
        "court": "ศาลแรงงานกลาง"
    },
    {
        "id": 4,
        "title": "คำร้องขอคุ้มครองชั่วคราว",
        "description": "คำร้องขอให้ศาลมีคำสั่งคุ้มครองชั่วคราว",
        "keywords": ["คุ้มครอง", "ชั่วคราว", "คำร้อง"],
        "court": "ศาลแรงงานกลาง"
    },
    {
        "id": 5,
        "title": "คำร้องอุทธรณ์คดีแรงงาน",
        "description": "คำร้องอุทธรณ์คำพิพากษาศาลแรงงาน",
        "keywords": ["อุทธรณ์", "คำพิพากษา", "แรงงาน"],
        "court": "ศาลแรงงานกลาง"
    }
]

def fuzzy_match(query: str, text: str) -> float:
    """Simple fuzzy matching score"""
    query_lower = query.lower()
    text_lower = text.lower()
    
    # Direct substring match
    if query_lower in text_lower:
        return 1.0
    
    # Word-based matching
    query_words = set(query_lower.split())
    text_words = set(text_lower.split())
    
    if not query_words:
        return 0.0
    
    common_words = query_words.intersection(text_words)
    return len(common_words) / len(query_words)

@router.get("/court-documents/search")
def search_court_documents(
    q: str = Query(..., min_length=1, description="Search query"),
    case_id: Optional[str] = None,
    texts: Optional[List[str]] = None,
    k: int = 5,
    step: Optional[int] = Query(None, description="Workflow step hint (e.g., 2 for plaintiff info)"),
    all_steps_data: Optional[str] = Query(None, description="JSON string of all steps data for Step 10"),
):
    """Suggest court document template using hybrid KG search with fuzzy fallback"""
    cid = case_id or latest_case_id()

    try:
        # Try hybrid search with Neo4j first
        doc_hits, facts = hybrid_search(q, case_id=cid, k=k)

        # Aggregate context
        pool_parts: List[str] = [q]
        pool_parts.extend([d.get("text", "") for d in doc_hits])
        for f in facts:
            pool_parts.append(str(f.get("person", "")))
            pool_parts.append(str(f.get("role", "")))
            pool_parts.append(str(f.get("amount", "")))
            pool_parts.append(str(f.get("date", "")))
        pool = " ".join(pool_parts).lower()

        suggestions: List[Dict] = []

        # Heuristic mapping from query+facts to document templates
        if any(kw in pool for kw in ["เลิกจ้างไม่เป็นธรรม", "เลิกจ้าง", "ไม่เป็นธรรม"]):
            suggestions.append({
                "id": 1,
                "title": "คำฟ้องคดีแรงงาน รง1",
                "description": "คำฟ้องคดีแรงงาน เลิกจ้างไม่เป็นธรรม",
                "keywords": ["คดีแรงงาน", "เลิกจ้าง", "ไม่เป็นธรรม", "คำฟ้อง", "รง1"],
                "court": "ศาลแรงงานกลาง",
                "score": max([d.get("score", 0.0) for d in doc_hits] or [0.8]),
            })

        if any(kw in pool for kw in ["ค่าจ้างค้างจ่าย", "ค่าจ้าง", "ค้างจ่าย", "ล่วงเวลา"]):
            suggestions.append({
                "id": 3,
                "title": "คำฟ้องคดีค่าจ้างค้างจ่าย รง1",
                "description": "คำฟ้องเรียกร้องค่าจ้างและค่าล่วงเวลา",
                "keywords": ["ค่าจ้าง", "ค้างจ่าย", "ค่าล่วงเวลา", "รง1"],
                "court": "ศาลแรงงานกลาง",
                "score": 0.7,
            })

        # If Neo4j worked but no suggestions, fallback to fuzzy
        if not suggestions:
            for doc in COURT_DOCUMENTS:
                title_score = fuzzy_match(q, doc["title"])
                desc_score = fuzzy_match(q, doc["description"]) * 0.8
                keyword_score = 0.0
                for keyword in doc.get("keywords", []):
                    keyword_score = max(keyword_score, fuzzy_match(q, keyword))
                keyword_score *= 0.9
                final_score = max(title_score, desc_score, keyword_score)
                if final_score > 0.2:
                    suggestions.append({**doc, "score": final_score})

    except Exception as e:
        # Neo4j failed, fallback to simple search
        print(f"Neo4j search failed: {e}, falling back to simple search")
        return search_court_documents_simple(q, case_id, k)

    # Optional: Step 2 support (parse plaintiff info using same endpoint)
    plaintiff_block: Optional[Dict] = None
    try:
        if step == 2:
            info = None
            source = "rule_based"
            try:
                info = llm_normalize_plaintiff(q)
                source = "llm"
            except Exception:
                info = parse_person_address(q)
                source = "rule_based"

            # build formatted Thai sentence
            name = ((info.get("title") or "") + (info.get("full_name") or "")).strip()
            parts: list[str] = []
            if name:
                parts.append(f"โจทก์ชื่อ {name}")
            if info.get("age") is not None:
                parts.append(f"อายุ {info['age']} ปี")
            addr = []
            if info.get("house_no"):
                addr.append(f"อยู่บ้านเลขที่ {info['house_no']}")
            loc = []
            if info.get("subdistrict"): loc.append(f"ตำบล{info['subdistrict']}")
            if info.get("district"): loc.append(f"อำเภอ{info['district']}")
            if info.get("province"): loc.append(f"จังหวัด{info['province']}")
            if info.get("postal_code"): loc.append(str(info["postal_code"]))
            if loc: addr.append(" ".join(loc))
            if addr: parts.append(" ".join(addr))
            formatted = " ".join(parts)

            resp = {
                "query": q,
                "case_id": cid,
                "results": suggestions[:5],
                "total": len(suggestions),
                "source": "hybrid_search",
                "plaintiff": {"parsed": info, "formatted": formatted, "normalize_source": source},
            }
            return resp
    except Exception:
        pass

    # Optional: Step 3 support (parse defendant info)
    defendant_block: Optional[Dict] = None
    try:
        if step == 3:
            from ..utils.thai_parser import parse_defendant_info
            info = parse_defendant_info(q)
            
            # Build formatted sentence
            parts: List[str] = []
            if info.get("entity_type") == "Company":
                if info.get("name"):
                    parts.append(f"จำเลยคือ {info['name']}")
            else:
                if info.get("name"):
                    parts.append(f"จำเลยชื่อ {info['name']}")
            
            # Address formatting
            addr = []
            if info.get("address"):
                addr.append(f"ตั้งอยู่ที่ {info['address']}")
            elif info.get("house_no") or info.get("street") or info.get("district") or info.get("province"):
                addr_parts = []
                if info.get("house_no"):
                    addr_parts.append(info["house_no"])
                if info.get("street"):
                    addr_parts.append(info["street"])
                if info.get("district"):
                    addr_parts.append(f"อำเภอ{info['district']}")
                if info.get("province"):
                    addr_parts.append(f"จังหวัด{info['province']}")
                if info.get("postal_code"):
                    addr_parts.append(info["postal_code"])
                if addr_parts:
                    addr.append(f"ตั้งอยู่ที่ {' '.join(addr_parts)}")
            
            if addr:
                parts.extend(addr)
            
            if info.get("phone"):
                parts.append(f"โทร. {info['phone']}")
            
            formatted = " ".join(parts)
            
            defendant_block = {
                "parsed": info,
                "formatted": formatted
            }
            
            # Store defendant info to Neo4j graph
            try:
                from ..utils.thai_parser import upsert_defendant_to_graph
                upsert_defendant_to_graph(info, cid)
            except Exception as e:
                print(f"Failed to store defendant to graph: {e}")
            
            resp = {
                "query": q,
                "case_id": cid,
                "results": suggestions[:5],
                "total": len(suggestions),
                "source": "hybrid_search",
                "defendant": defendant_block,
            }
            return resp
    except Exception as e:
        print(f"Step 3 parsing failed: {e}")
        pass

    # Optional: Step 4 support (parse employment info)
    employment_block: Optional[Dict] = None
    try:
        if step == 4:
            from ..utils.thai_parser import parse_employment_info, format_employment_summary, calculate_labor_law_interest, calculate_severance_pay, calculate_advance_notice_pay
            info = parse_employment_info(q)
            
            # Format summary
            formatted = format_employment_summary(info, cid)
            
            # Calculate severance pay
            severance_calculation = None
            if info.get("daily_wage") and info.get("years") is not None:
                severance_calculation = calculate_severance_pay(
                    info["daily_wage"], 
                    info.get("years", 0), 
                    info.get("months", 0)
                )
            
            # Calculate potential interest/penalty (example with 30 days overdue)
            interest_calculation = None
            if info.get("daily_wage"):
                # Example calculation for unpaid wages (30 days)
                unpaid_amount = info["daily_wage"] * 30  # Assume 30 days unpaid
                interest_calculation = calculate_labor_law_interest(unpaid_amount, 30)
            
            # Calculate advance notice pay
            advance_notice_calculation = None
            if info.get("daily_wage"):
                advance_notice_calculation = calculate_advance_notice_pay(
                    info["daily_wage"],
                    info.get("payment_period", "รายเดือน"),
                    info.get("termination_reason", "เลิกจ้างโดยนายจ้าง")
                )
            
            employment_block = {
                "parsed": info,
                "formatted": formatted,
                "severance_calculation": severance_calculation,
                "interest_calculation": interest_calculation,
                "advance_notice_calculation": advance_notice_calculation
            }
            
            # Store employment info to Neo4j graph
            try:
                from ..utils.thai_parser import upsert_employment_to_graph
                upsert_employment_to_graph(info, cid)
            except Exception as e:
                print(f"Failed to store employment to graph: {e}")
            
            resp = {
                "query": q,
                "case_id": cid,
                "results": suggestions[:5],
                "total": len(suggestions),
                "source": "hybrid_search",
                "employment": employment_block,
            }
            return resp
    except Exception as e:
        print(f"Step 4 parsing failed: {e}")
        pass

    # Optional: Step 5 support (parse termination info)
    termination_block: Optional[Dict] = None
    try:
        if step == 5:
            from ..utils.thai_parser import parse_termination_info, format_termination_summary, upsert_termination_to_graph
            info = parse_termination_info(q)
            
            # Format summary
            formatted = format_termination_summary(info, cid)
            
            termination_block = {
                "parsed": info,
                "formatted": formatted,
                "legal_summary": info.get("legal_summary", ""),
                "violations": info.get("violations", []),
                "violation_count": info.get("violation_count", 0)
            }
            
            # Store termination info to Neo4j graph
            try:
                upsert_termination_to_graph(info, cid)
            except Exception as e:
                print(f"Failed to store termination to graph: {e}")
            
            resp = {
                "query": q,
                "case_id": cid,
                "results": suggestions[:5],
                "total": len(suggestions),
                "source": "hybrid_search",
                "termination": termination_block,
            }
            return resp
    except Exception as e:
        print(f"Step 5 parsing failed: {e}")
        pass

    # Optional: Step 6 support (parse court claims)
    claims_block: Optional[Dict] = None
    try:
        if step == 6:
            from ..utils.thai_parser import parse_court_claims, format_court_claims_summary, upsert_court_claims_to_graph
            info = parse_court_claims(q)
            
            # Format summary
            formatted = format_court_claims_summary(info, cid)
            
            claims_block = {
                "parsed": info,
                "formatted": formatted,
                "formal_request": info.get("formal_request", ""),
                "detected_claims": info.get("detected_claims", []),
                "claim_count": info.get("claim_count", 0)
            }
            
            # Store court claims to Neo4j graph
            try:
                upsert_court_claims_to_graph(info, cid)
            except Exception as e:
                print(f"Failed to store court claims to graph: {e}")
            
            resp = {
                "query": q,
                "case_id": cid,
                "results": suggestions[:5],
                "total": len(suggestions),
                "source": "hybrid_search",
                "claims": claims_block,
            }
            return resp
    except Exception as e:
        print(f"Step 6 parsing failed: {e}")
        pass

    # Optional: Step 7 support (financial summary)
    financial_block: Optional[Dict] = None
    try:
        if step == 7:
            from ..utils.thai_parser import parse_financial_summary, format_financial_summary, upsert_financial_summary_to_graph
            
            # Try to get employment data from Step 4 first
            employment_info = None
            severance_info = None
            advance_notice_info = None
            
            # Re-run Step 4 parsing to get financial data
            try:
                from ..utils.thai_parser import parse_employment_info, calculate_severance_pay, calculate_advance_notice_pay
                
                # Try to get Step 4 data from session/cache or re-parse
                # For now, we'll assume the user has gone through Step 4
                # In a real implementation, you might want to store this in session or database
                
                # Parse financial summary with available data
                info = parse_financial_summary(
                    q, 
                    employment_info=employment_info,
                    advance_notice_info=advance_notice_info,
                    severance_info=severance_info
                )
                
            except Exception as e:
                print(f"Failed to get Step 4 data for financial summary: {e}")
                # Parse without Step 4 data
                info = parse_financial_summary(q)
            
            # Format summary
            formatted = format_financial_summary(info, cid)
            
            financial_block = {
                "parsed": info,
                "formatted": formatted,
                "formal_summary": info.get("formal_summary", ""),
                "requested_amount": info.get("requested_amount"),
                "calculated_total": info.get("calculated_total", 0),
                "calculations": info.get("calculations", {}),
                "has_calculations": info.get("has_calculations", False)
            }
            
            # Store financial summary to Neo4j graph
            try:
                upsert_financial_summary_to_graph(info, cid)
            except Exception as e:
                print(f"Failed to store financial summary to graph: {e}")
            
            resp = {
                "query": q,
                "case_id": cid,
                "results": suggestions[:5],
                "total": len(suggestions),
                "source": "hybrid_search",
                "financial": financial_block,
            }
            return resp
    except Exception as e:
        print(f"Step 7 parsing failed: {e}")
        pass

    # Optional: Step 8 support (legal references)
    legal_block: Optional[Dict] = None
    try:
        if step == 8:
            from ..utils.thai_parser import parse_legal_references, format_legal_references, upsert_legal_references_to_graph
            
            # Try to get context from previous steps
            # In a real implementation, you'd fetch this from session/database
            employment_context = None
            termination_context = None
            claims_context = None
            financial_context = None
            
            # Parse legal references with context
            info = parse_legal_references(
                q,
                employment_info=employment_context,
                termination_info=termination_context,
                claims_info=claims_context,
                financial_info=financial_context
            )
            
            # Format citation
            formatted = format_legal_references(info, cid)
            
            legal_block = {
                "parsed": info,
                "formatted": formatted,
                "formal_citation": info.get("formal_citation", ""),
                "legal_references": info.get("legal_references", []),
                "detected_topics": info.get("detected_topics", []),
                "reference_count": info.get("reference_count", 0),
                "primary_law": info.get("primary_law", "")
            }
            
            # Store legal references to Neo4j graph
            try:
                upsert_legal_references_to_graph(info, cid)
            except Exception as e:
                print(f"Failed to store legal references to graph: {e}")
            
            resp = {
                "query": q,
                "case_id": cid,
                "results": suggestions[:5],
                "total": len(suggestions),
                "source": "hybrid_search",
                "legal": legal_block,
            }
            return resp
    except Exception as e:
        print(f"Step 8 parsing failed: {e}")
        pass

    # Optional: Step 9 support (court petition)
    petition_block: Optional[Dict] = None
    try:
        if step == 9:
            from ..utils.thai_parser import parse_court_petition, format_court_petition, upsert_court_petition_to_graph
            
            # Parse court petition
            info = parse_court_petition(q)
            
            # Format petition
            formatted = format_court_petition(info, cid)
            
            petition_block = {
                "parsed": info,
                "formatted": formatted,
                "formal_petition": info.get("formal_petition", ""),
                "detected_claims": info.get("detected_claims", []),
                "legal_articles": info.get("legal_articles", []),
                "primary_law": info.get("primary_law", ""),
                "secondary_laws": info.get("secondary_laws", []),
                "claim_count": info.get("claim_count", 0),
                "article_count": info.get("article_count", 0),
                "assessment": info.get("assessment", "")
            }
            
            # Store petition to Neo4j graph
            try:
                upsert_court_petition_to_graph(info, cid)
            except Exception as e:
                print(f"Failed to store court petition to graph: {e}")
            
            resp = {
                "query": q,
                "case_id": cid,
                "results": suggestions[:5],
                "total": len(suggestions),
                "source": "hybrid_search",
                "petition": petition_block,
            }
            return resp
    except Exception as e:
        print(f"Step 9 parsing failed: {e}")
        pass

    # Optional: Step 10 support (complete document compilation)
    document_block: Optional[Dict] = None
    try:
        if step == 10:
            from ..utils.thai_parser import parse_signature_and_compile_document, format_complete_document, upsert_complete_document_to_graph
            
            # Get all steps data from query parameter or use empty data
            signature_text = q
            steps_data = {}
            
            if all_steps_data:
                try:
                    import json
                    steps_data = json.loads(all_steps_data)
                    print(f"Received steps data for Step 10: {len(steps_data)} steps")
                except Exception as e:
                    print(f"Failed to parse all_steps_data JSON: {e}")
                    steps_data = {}
            else:
                # No steps data provided, will show just signature
                steps_data = {}
            
            # Parse signature and compile complete document
            info = parse_signature_and_compile_document(signature_text, steps_data)
            
            # Format complete document
            formatted = format_complete_document(info, cid)
            
            document_block = {
                "parsed": info,
                "formatted": formatted,
                "compiled_document": info.get("compiled_document", ""),
                "signature_info": info.get("signature_info", {}),
                "document_sections": info.get("document_sections", []),
                "total_sections": info.get("total_sections", 0),
                "total_words": info.get("total_words", 0),
                "total_lines": info.get("total_lines", 0),
                "completion_percentage": info.get("completion_percentage", 0),
                "document_summary": info.get("document_summary", "")
            }
            
            # Store complete document to Neo4j graph
            try:
                upsert_complete_document_to_graph(info, cid)
            except Exception as e:
                print(f"Failed to store complete document to graph: {e}")
            
            resp = {
                "query": signature_text,
                "case_id": cid,
                "results": suggestions[:5],
                "total": len(suggestions),
                "source": "hybrid_search",
                "document": document_block,
            }
            return resp
    except Exception as e:
        print(f"Step 10 parsing failed: {e}")
        pass

    # Sort and return
    suggestions.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    resp = {
        "query": q,
        "case_id": cid,
        "results": suggestions[:5],
        "total": len(suggestions),
        "source": "hybrid_search",
    }
    if plaintiff_block:
        resp["plaintiff"] = plaintiff_block
    return resp


@router.post("/plaintiff/ingest")
def ingest_plaintiff_info(
    text: str = Query(..., min_length=1, description="ข้อความข้อมูลโจทก์และที่อยู่"),
    case_id: Optional[str] = Query(None, description="ระบุ case_id ถ้าต้องการผูกเข้ากับคดีเฉพาะ")
):
    """Parse plaintiff person/address text and upsert person + address graph."""
    setup_constraints()

    info = parse_person_address(text)

    # Build graph doc
    nodes: List[SimpleNode] = []
    rels: List[SimpleRel] = []

    # Person
    full_name = info.get("full_name") or "โจทก์"
    title = info.get("title") or ""
    age = info.get("age")
    person = SimpleNode(f"{title}{full_name}".strip(), "Person")
    nodes.append(person)
    role = SimpleNode("Plaintiff", "LegalRole")
    nodes.append(role)
    rels.append(SimpleRel(person, role, "HAS_ROLE"))

    # Address
    addr_label = []
    if info.get("house_no"):
        addr_label.append(f"บ้านเลขที่ {info['house_no']}")
    address_name = " ".join(addr_label) or "ที่อยู่"
    address = SimpleNode(address_name, "Address")
    nodes.append(address)
    rels.append(SimpleRel(person, address, "RESIDES_AT"))

    # Hierarchy: Subdistrict -> District -> Province
    sd = info.get("subdistrict")
    if sd:
        sd_node = SimpleNode(sd, "Subdistrict")
        nodes.append(sd_node)
        rels.append(SimpleRel(address, sd_node, "IN_SUBDISTRICT"))

    dist = info.get("district")
    if dist:
        dist_node = SimpleNode(dist, "District")
        nodes.append(dist_node)
        # link from address if no subdistrict
        rels.append(SimpleRel(address, dist_node, "IN_DISTRICT"))

    prov = info.get("province")
    if prov:
        prov_node = SimpleNode(prov, "Province")
        nodes.append(prov_node)
        rels.append(SimpleRel(address, prov_node, "IN_PROVINCE"))

    # Postal code
    pc = info.get("postal_code")
    if pc:
        pc_node = SimpleNode(pc, "PostalCode")
        nodes.append(pc_node)
        rels.append(SimpleRel(address, pc_node, "HAS_POSTAL_CODE"))

    gd = SimpleGraphDocument(nodes, rels)
    # Attach to provided case or latest
    cid = (case_id or latest_case_id() or "PLAINTIFF-INFO").strip()
    upsert_graph([gd], cid)

    return {"case_id": cid, "parsed": info}


@router.get("/court-documents/search-simple")
def search_court_documents_simple(
    q: str = Query(..., min_length=1, description="Search query"),
    case_id: Optional[str] = None,
    k: int = 5,
):
    """Simple court document search using fuzzy matching only"""
    cid = case_id or "simple_case"

    suggestions: List[Dict] = []

    # Direct fuzzy matching over static list
    for doc in COURT_DOCUMENTS:
        title_score = fuzzy_match(q, doc["title"])
        desc_score = fuzzy_match(q, doc["description"]) * 0.8
        keyword_score = 0.0
        for keyword in doc.get("keywords", []):
            keyword_score = max(keyword_score, fuzzy_match(q, keyword))
        keyword_score *= 0.9
        final_score = max(title_score, desc_score, keyword_score)
        if final_score > 0.1:  # Lower threshold for better results
            suggestions.append({**doc, "score": final_score})

    # Sort and return
    suggestions.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return {
        "query": q,
        "case_id": cid,
        "results": suggestions[:k],
        "total": len(suggestions),
        "source": "simple_search"
    }


@router.post("/setup/provinces")
async def setup_thai_provinces():
    """Setup Thai provinces in Neo4j graph"""
    try:
        from ..utils.thai_parser import upsert_thai_provinces
        upsert_thai_provinces()
        return {"message": "Thai provinces added successfully", "count": 77}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Setup failed: {str(e)}")
