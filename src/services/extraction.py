"""Rule-based text extraction service"""

import re
import hashlib
from typing import List
from ..models.graph import SimpleNode, SimpleRel, SimpleGraphDocument
from ..utils.thai_parser import normalize_thai_digits, parse_thai_amount, parse_thai_date_iso


def rule_based_extract(text: str) -> List[SimpleGraphDocument]:
    """Extract entities and relationships from text using rule-based approach"""
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

    s = normalize_thai_digits(text)

    # Parties
    plaintiff = get_node("โจทก์", "Person") if re.search(r"โจทก(์)?", s) else None
    defendant = get_node("จำเลย", "Person") if "จำเลย" in s else None

    # Employment
    if any(kw in s for kw in ["จ้าง", "เข้าทำงาน", "ลูกจ้าง", "ทำงาน"]):
        contract = get_node("สัญญาจ้างงาน", "EmploymentContract")
        if plaintiff:
            rels.append(SimpleRel(plaintiff, contract, "EMPLOYED_BY"))

    # Money/Amounts
    if "บาท" in s:
        amt = parse_thai_amount(s)
        if amt is not None:
            money = get_node(f"{int(amt):,} บาท", "MoneyAmount")
            term_name = "จำนวนเงิน"  # Generic amount
            if "ปรับ" in s:
                term_name = "ค่าปรับ"
            elif "ค่าชดเชย" in s:
                term_name = "ค่าชดเชย"
            
            term = get_node(term_name, "LegalTerm")
            rels.append(SimpleRel(term, money, "HAS_AMOUNT"))

    # Dates
    iso = parse_thai_date_iso(s)
    if iso:
        date = get_node(iso, "Date")
        if plaintiff:
            rels.append(SimpleRel(plaintiff, date, "OCCURRED_ON"))

    # Group
    group = None
    m_group = re.search(r"หมวด\s*(\d+)", s)
    if m_group:
        group_no = m_group.group(1)
        group = get_node(f"หมวด {group_no}", "Group")

    # Section + Section_desc
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


def detect_case_id(texts: List[str]) -> str:
    """Detect or generate case ID from text chunks"""
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
    
    # Generate hash-based ID if no case number found
    h = hashlib.sha1("\n".join(texts).encode("utf-8")).hexdigest()[:10]
    return f"CASE-{h}"
