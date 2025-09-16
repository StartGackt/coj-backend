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

    # --- Legal structure: Act / Book / Title / Chapter / Part ---
    act = None
    # e.g., พระราชบัญญัติแรงงาน พ.ศ. 2541 / ประมวลกฎหมายอาญา พ.ศ. 2499
    m_act = re.search(r"((?:พระราชบัญญัติ|ประมวลกฎหมาย)[^\n]*?พ\.ศ\.?\s*\d{4})", s)
    if m_act:
        act_name = m_act.group(1).strip()
        act = get_node(act_name, "Act")

    book = None
    # e.g., ลักษณะ 1, ลักษณะหนึ่ง
    m_book = re.search(r"ลักษณะ\s*([\d]+|[\u0E00-\u0E7F]+)", s)
    if m_book:
        book_no = m_book.group(1).strip()
        book = get_node(f"ลักษณะ {book_no}", "Book")

    title = None
    # e.g., บททั่วไป, บทกำหนดโทษ
    m_title = re.search(r"บท\s*([\u0E00-\u0E7F]+)", s)
    if m_title:
        title_name = m_title.group(1).strip()
        title = get_node(f"บท {title_name}", "Title")

    chapter = None
    # e.g., หมวด 16 บทกำหนดโทษ
    m_chapter = re.search(r"หมวด\s*(\d+)", s)
    if m_chapter:
        chapter_no = m_chapter.group(1)
        chapter = get_node(f"หมวด {chapter_no}", "Chapter")

    part = None
    # e.g., ตอน 1, ตอนที่ 2
    m_part = re.search(r"ตอน(?:ที่)?\s*(\d+)", s)
    if m_part:
        part_no = m_part.group(1)
        part = get_node(f"ตอน {part_no}", "Part")

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

    # --- Wire hierarchy with BELONGS_TO (lowest -> highest) ---
    # Section -> Part/Chapter/Title/Book/Act
    if section:
        if part:
            rels.append(SimpleRel(section, part, "BELONGS_TO"))
        elif chapter:
            rels.append(SimpleRel(section, chapter, "BELONGS_TO"))
        elif title:
            rels.append(SimpleRel(section, title, "BELONGS_TO"))
        elif book:
            rels.append(SimpleRel(section, book, "BELONGS_TO"))
        elif act:
            rels.append(SimpleRel(section, act, "BELONGS_TO"))

    # Part -> Chapter/Title/Book/Act
    if part:
        if chapter:
            rels.append(SimpleRel(part, chapter, "BELONGS_TO"))
        elif title:
            rels.append(SimpleRel(part, title, "BELONGS_TO"))
        elif book:
            rels.append(SimpleRel(part, book, "BELONGS_TO"))
        elif act:
            rels.append(SimpleRel(part, act, "BELONGS_TO"))

    # Chapter -> Title/Book/Act
    if chapter:
        if title:
            rels.append(SimpleRel(chapter, title, "BELONGS_TO"))
        elif book:
            rels.append(SimpleRel(chapter, book, "BELONGS_TO"))
        elif act:
            rels.append(SimpleRel(chapter, act, "BELONGS_TO"))

    # Title -> Book/Act
    if title:
        if book:
            rels.append(SimpleRel(title, book, "BELONGS_TO"))
        elif act:
            rels.append(SimpleRel(title, act, "BELONGS_TO"))

    # Book -> Act
    if book and act:
        rels.append(SimpleRel(book, act, "BELONGS_TO"))

    # Backward compatibility: Group (legacy) and link Section -> Group via SECTION
    group = None
    m_group = re.search(r"หมวด\s*(\d+)", s)
    if m_group:
        group_no = m_group.group(1)
        group = get_node(f"หมวด {group_no}", "Group")
    if group and section:
        rels.append(SimpleRel(section, group, "SECTION"))

    # --- Paragraphs, Interest, Penalties, TimePeriods, Cross-refs ---
    # Paragraph segmentation
    paragraph_spans = []  # list of (para_no, start_idx, end_idx)
    for m in re.finditer(r"วรรคที่\s*(\d+)", s):
        try:
            no = int(m.group(1))
        except Exception:
            continue
        paragraph_spans.append((no, m.start(), None))
    # Close spans
    for i in range(len(paragraph_spans)):
        no, start, _ = paragraph_spans[i]
        end = paragraph_spans[i + 1][1] if i + 1 < len(paragraph_spans) else len(s)
        paragraph_spans[i] = (no, start, end)

    # Helper to add InterestRate from text
    def extract_interest_rate(text_segment: str, owner_node: SimpleNode):
        m_rate = re.search(r"ดอกเบี้ย(?:ร้อยละ)?\s*(\d+(?:\.\d+)?)\s*ต่อ\s*(ปี|เดือน)", text_segment)
        if m_rate:
            rate_val = m_rate.group(1)
            period = m_rate.group(2)
            rate_node = get_node(f"{rate_val}% ต่อ{period}", "InterestRate")
            rels.append(SimpleRel(owner_node, rate_node, "HAS_RATE"))

    # Helper to add Penalty and TimePeriod from text
    def extract_penalty(text_segment: str, owner_node: SimpleNode):
        m_pen = re.search(r"(เงินเพิ่ม|เบี้ยปรับ)[^\d%]*?(?:ร้อยละ)?\s*(\d+(?:\.\d+)?)", text_segment)
        if m_pen:
            rate_val = m_pen.group(2)
            pen_node = get_node(f"เงินเพิ่ม {rate_val}%", "Penalty")
            rels.append(SimpleRel(owner_node, pen_node, "HAS_PENALTY"))

            # Time period e.g., ทุก 7 วัน / ทุกระยะเวลาเจ็ดวัน
            m_tp = re.search(r"(?:ทุก(?:ระยะเวลา)?\s*)(\d+|เจ็ด)\s*วัน", text_segment)
            if m_tp:
                val = m_tp.group(1)
                if val == "เจ็ด":
                    val = "7"
                tp_node = get_node(f"ทุก {val} วัน", "TimePeriod")
                rels.append(SimpleRel(pen_node, tp_node, "WITHIN"))

    # If paragraphs exist, attach findings to each paragraph
    created_paragraphs = []
    if section and paragraph_spans:
        for no, start, end in paragraph_spans:
            seg_text = s[start:end]
            para_node = get_node(f"วรรคที่ {no}", "Paragraph")
            rels.append(SimpleRel(section, para_node, "HAS_PARAGRAPH"))
            created_paragraphs.append((para_node, seg_text))
            extract_interest_rate(seg_text, para_node)
            extract_penalty(seg_text, para_node)
            # Extract causes per paragraph
            # Examples: ไม่คืนหลักประกัน, ไม่จ่ายค่าจ้าง, ไม่จ่ายเงินกรณี..., ไม่จ่ายเงิน...ตามมาตรา xx
            for m_cause in re.finditer(r"(ไม่คืน[^,;\n]+|ไม่จ่าย[^,;\n]+)", seg_text):
                cause_text = m_cause.group(1).strip()
                cause_node = get_node(cause_text, "Cause")
                rels.append(SimpleRel(para_node, cause_node, "HAS_CAUSE"))
                # Cross-refs inside cause
                for m_ref in re.finditer(r"มาตรา\s*(\d+(?:\s*/\s*\d+)?)", cause_text):
                    ref_raw = m_ref.group(1)
                    ref_norm = re.sub(r"\s*/\s*", "/", ref_raw)
                    ref_node = get_node(f"มาตรา {ref_norm}", "Section")
                    rels.append(SimpleRel(cause_node, ref_node, "REFERS_TO"))
    else:
        # Fallback: attach to section
        if section:
            extract_interest_rate(s, section)
            extract_penalty(s, section)
            for m_cause in re.finditer(r"(ไม่คืน[^,;\n]+|ไม่จ่าย[^,;\n]+)", s):
                cause_text = m_cause.group(1).strip()
                cause_node = get_node(cause_text, "Cause")
                rels.append(SimpleRel(section, cause_node, "HAS_CAUSE"))
                for m_ref in re.finditer(r"มาตรา\s*(\d+(?:\s*/\s*\d+)?)", cause_text):
                    ref_raw = m_ref.group(1)
                    ref_norm = re.sub(r"\s*/\s*", "/", ref_raw)
                    ref_node = get_node(f"มาตรา {ref_norm}", "Section")
                    rels.append(SimpleRel(cause_node, ref_node, "REFERS_TO"))

    # Cross-referenced sections: มาตรา 10, มาตรา 17/1, 120 / 1, etc.
    if section:
        current_no_match = re.search(r"มาตรา\s*(\d+)", s)
        current_no = current_no_match.group(1) if current_no_match else None
        for m in re.finditer(r"มาตรา\s*(\d+(?:\s*/\s*\d+)?)", s):
            ref_raw = m.group(1)
            # Normalize 120 / 1 -> 120/1
            ref_norm = re.sub(r"\s*/\s*", "/", ref_raw)
            # Skip self-reference
            if current_no and ref_norm == current_no:
                continue
            ref_node = get_node(f"มาตรา {ref_norm}", "Section")
            rels.append(SimpleRel(section, ref_node, "REFERS_TO"))

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
