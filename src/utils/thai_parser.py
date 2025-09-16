"""Thai text parsing utilities"""

import re
from typing import Optional, List, Dict
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


# --- Person / Address parsing ---
def parse_person_address(text: str) -> Dict:
    """Parse Thai free text into person + address fields.
    Returns dict with keys: title, name_parts, full_name, age, house_no, subdistrict, district, province, postal_code
    """
    s = normalize_thai_digits((text or "").strip())

    # Age
    age: Optional[int] = None
    m_age = re.search(r"(?:อายุ\s*)?(\d{1,3})\s*ปี", s)
    if m_age:
        try:
            age = int(m_age.group(1))
        except Exception:
            age = None
    s_wo_age = re.sub(r"(?:อายุ\s*)?\d{1,3}\s*ปี", " ", s)

    # Title
    title = None
    m_title = re.search(r"(นาย|นางสาว|นาง|เด็กชาย|เด็กหญิง)", s_wo_age)
    if m_title:
        title = m_title.group(1)

    # Name zone
    name_zone = s_wo_age
    m_after_chue = re.search(r"ชื่อ\s*([\u0E00-\u0E7F\s]+)", s_wo_age)
    if m_after_chue:
        name_zone = m_after_chue.group(1)
    name_zone = re.split(r"(อยู่|จังหวัด|เขต|อำเภอ|ตำบล|แขวง|บ้านเลขที่|รหัสไปรษณี|รหัสไปรษณีย์)", name_zone)[0]

    m_name = re.search(
        r"(?:นาย|นางสาว|นาง|เด็กชาย|เด็กหญิง)?\s*" \
        r"([\u0E00-\u0E7F]+)" \
        r"(?:\s+([\u0E00-\u0E7F]+))?" \
        r"(?:\s+([\u0E00-\u0E7F]+))?",
        name_zone.strip()
    )
    name_parts: List[str] = []
    if m_name:
        for i in range(1, 4):
            part = m_name.group(i)
            if part and part not in {"นาย", "นางสาว", "นาง", "เด็กชาย", "เด็กหญิง"}:
                name_parts.append(part)

    # Address pieces
    house_no = None
    m_house = re.search(r"บ้านเลขที่\s*([\w\-\/]+)", s)
    if m_house:
        house_no = m_house.group(1)

    # Subdistrict/แขวง, District/เขต อำเภอ, Province จังหวัด
    subdistrict = None
    district = None
    province = None

    m_sd = re.search(r"(?:ต\.|ตำบล|แขวง)\s*([\u0E00-\u0E7F]+)", s)
    if m_sd:
        subdistrict = m_sd.group(1)
    m_d = re.search(r"(?:อ\.|อำเภอ|เขต)\s*([\u0E00-\u0E7F]+)", s)
    if m_d:
        district = m_d.group(1)
    m_p = re.search(r"(?:จ\.|จังหวัด)\s*([\u0E00-\u0E7F]+)", s)
    if m_p:
        province = m_p.group(1)
    else:
        # Try infer from pattern: (อำเภอ|เขต) <district> <province>
        m_dp = re.search(r"(?:อ\.|อำเภอ|เขต)\s*([\u0E00-\u0E7F]+)\s+([\u0E00-\u0E7F]+)", s)
        if m_dp:
            district = district or m_dp.group(1)
            province = m_dp.group(2)
        else:
            m_stay = re.search(r"อยู่\s*([\u0E00-\u0E7F]+)", s)
            if m_stay:
                province = m_stay.group(1)

    # Normalize province Bangkok variants
    if province in {"กทม", "กรุงเทพ", "กรุงเทพฯ"}:
        province = "กรุงเทพมหานคร"

    # If district is generic 'เมือง' and province known, expand
    if district == "เมือง" and province:
        district = f"เมือง{province}"

    # Postal code
    postal_code = None
    m_pc = re.search(r"รหัสไปรษณ(?:ี|ีย์)\s*(\d{5})", s)
    if m_pc:
        postal_code = m_pc.group(1)

    if not title and name_parts:
        title = "นาย"

    full_name = " ".join(name_parts).strip()

    return {
        "title": title,
        "name_parts": name_parts,
        "full_name": full_name,
        "age": age,
        "house_no": house_no,
        "subdistrict": subdistrict,
        "district": district,
        "province": province,
        "postal_code": postal_code,
    }
