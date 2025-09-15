"""Thai text parsing utilities"""

import re
from typing import Optional, List
from pythainlp import word_tokenize
from pythainlp.util import thaiword_to_num

from ..config import THAI_MONTHS, THAI_DIGITS


def normalize_thai_digits(text: str) -> str:
    """Convert Thai digits to Arabic digits"""
    return text.translate(THAI_DIGITS)


def parse_thai_amount(text: str) -> Optional[float]:
    """Extract Thai money amount from text, handling both digits and words."""
    if not text or "บาท" not in text:
        return None

    # First, try to match standard digits (e.g., "10,000.50 บาท")
    m_digit = re.search(r"([0-9,]+(?:\.[0-9]+)?)\s*บาท", text)
    if m_digit:
        try:
            return float(m_digit.group(1).replace(",", ""))
        except (ValueError, IndexError):
            pass  # Fall through to word-based parser

    # Second, try to match Thai number words (e.g., "หนึ่งหมื่นบาท")
    m_word = re.search(
        r"(?:ปรับ|ค่า|เป็นเงิน|จำนวน|ไม่เกิน|กว่า)\s*([\u0E00-\u0E39\s]+?)\s*บาท", text
    )
    if m_word:
        num_text = m_word.group(1).strip()
        try:
            # Use pythainlp's utility to convert Thai words to a number
            return float(thaiword_to_num(num_text))
        except (ValueError, IndexError):
            pass  # If conversion fails, do nothing

    return None


def parse_thai_date_iso(text: str) -> Optional[str]:
    """Parse Thai date to ISO format (YYYY-MM-DD)"""
    if not text:
        return None
    s = text.strip()
    
    # Pattern: DD month YYYY
    m = re.search(r"(\d{1,2})\s+([\u0E00-\u0E7F]+)\s+(\d{4})", s)
    if m:
        d = int(m.group(1))
        mon_name = m.group(2)
        y = int(m.group(3))
        mon = THAI_MONTHS.get(mon_name)
        if mon:
            if y > 2400:  # Buddhist year to Gregorian
                y -= 543
            return f"{y:04d}-{mon:02d}-{d:02d}"
    
    # Pattern: month YYYY
    m2 = re.search(r"([\u0E00-\u0E7F]+)\s+(\d{4})", s)
    if m2:
        mon_name = m2.group(1)
        y = int(m2.group(2))
        mon = THAI_MONTHS.get(mon_name)
        if mon:
            if y > 2400:  # Buddhist year to Gregorian
                y -= 543
            return f"{y:04d}-{mon:02d}"
    
    return None


def tokenize(s: str) -> List[str]:
    """Smart Thai/English tokenizer using pythainlp"""
    if not s:
        return []
    s = normalize_thai_digits(s.lower())
    toks = word_tokenize(s)
    return [t for t in toks if t and not t.isspace()]


def sanitize_label(label: str) -> str:
    """Sanitize string to be a valid Neo4j label"""
    label = label or "Entity"
    label = re.sub(r"[^A-Za-z0-9_]", "_", label)
    if not label:
        label = "Entity"
    if label[0].isdigit():
        label = f"_{label}"
    return label


def sanitize_rel_type(rtype: str) -> str:
    """Sanitize string to be a valid Neo4j relationship type"""
    rtype = (rtype or "RELATES_TO").upper()
    rtype = re.sub(r"[^A-Z0-9_]", "_", rtype)
    if not rtype:
        rtype = "RELATES_TO"
    if rtype[0].isdigit():
        rtype = f"R_{rtype}"
    return rtype
