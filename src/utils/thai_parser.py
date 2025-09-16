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
    m_pc = re.search(r"รหัสไปรษ(?:ี|ีย์)\s*(\d{5})", s)
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


# รายชื่อจังหวัดไทยทั้งหมด 77 จังหวัด
THAI_PROVINCES = {
    "กรุงเทพมหานคร", "สมุทรปราการ", "นนทบุรี", "ปทุมธานี", "พระนครศรีอยุธยา",
    "อ่างทอง", "ลพบุรี", "สิงห์บุรี", "ชัยนาท", "สระบุรี", "ชลบุรี", "ระยอง",
    "จันทบุรี", "ตราด", "ฉะเชิงเทรา", "ปราจีนบุรี", "นครนายก", "สระแก้ว",
    "นครราชสีมา", "บุรีรัมย์", "สุรินทร์", "ศรีสะเกษ", "อุบลราชธานี", "ยโสธร",
    "ชัยภูมิ", "อำนาจเจริญ", "หนองบัวลำภู", "ขอนแก่น", "อุดรธานี", "เลย",
    "หนองคาย", "มหาสารคาม", "ร้อยเอ็ด", "กาฬสินธุ์", "สกลนคร", "นครพนม",
    "มุกดาหาร", "เชียงใหม่", "ลำพูน", "ลำปาง", "อุตรดิตถ์", "แพร่", "น่าน",
    "พะเยา", "เชียงราย", "แม่ฮ่องสอน", "นครสวรรค์", "อุทัยธานี", "กำแพงเพชร",
    "ตาก", "สุโขทัย", "พิษณุโลก", "พิจิตร", "เพชรบูรณ์", "ราชบุรี", "กาญจนบุรี",
    "สุพรรณบุรี", "นครปฐม", "สมุทรสาคร", "สมุทรสงคราม", "เพชรบุรี", "ประจวบคีรีขันธ์",
    "นครศรีธรรมราช", "กระบี่", "พังงา", "ภูเก็ต", "สุราษฎร์ธานี", "ระนอง",
    "ชุมพร", "สงขลา", "สตูล", "ตรัง", "พัทลุง", "ปัตตานี", "ยะลา", "นราธิวาส",
    "บึงกาฬ"
}

# Province aliases สำหรับ normalization
PROVINCE_ALIASES = {
    "กทม": "กรุงเทพมหานคร",
    "กรุงเทพ": "กรุงเทพมหานคร", 
    "กรุงเทพฯ": "กรุงเทพมหานคร",
    "บกค": "บึงกาฬ",
    "อจ": "อำนาจเจริญ",
    "นบล": "หนองบัวลำภู",
    "สกน": "สกลนคร"
}

def llm_normalize_plaintiff(text: str) -> Dict:
    """Normalize plaintiff info using LLM with fallback to rule-based parsing."""
    # เริ่มต้นด้วย rule-based parsing
    data = parse_person_address(text)
    
    # Normalize province aliases
    if data.get("province") in PROVINCE_ALIASES:
        data["province"] = PROVINCE_ALIASES[data["province"]]
    
    # เติมค่าที่ขาดจากข้อความดิบ
    data = _infer_from_text(text, data)
    
    # Validate province against known list
    if data.get("province") and data["province"] not in THAI_PROVINCES:
        # Try to find closest match in THAI_PROVINCES
        province_text = data["province"]
        for p in THAI_PROVINCES:
            if province_text in p or p in province_text:
                data["province"] = p
                break
    
    return {
        "title": data.get("title"),
        "name_parts": (data.get("full_name") or "").split() if data.get("full_name") else None,
        "full_name": data.get("full_name"),
        "age": data.get("age"),
        "house_no": data.get("house_no"),
        "subdistrict": data.get("subdistrict"),
        "district": data.get("district"),
        "province": data.get("province"),
        "postal_code": data.get("postal_code"),
    }


def _infer_from_text(raw: str, data: Dict) -> Dict:
    s = normalize_thai_digits((raw or "").strip())

    # province fallback: กทม / กรุงเทพฯ / กรุงเทพ หรือ "จังหวัด ..."
    if not data.get("province"):
        if ("กทม" in s) or ("กรุงเทพฯ" in s) or ("กรุงเทพ" in s):
            data["province"] = "กรุงเทพมหานคร"
        else:
            m_p = re.search(r"จังหวัด\s*([\u0E00-\u0E7F]+)", s)
            if m_p:
                data["province"] = m_p.group(1)

    # house_no fallback: ตัวเลข 1-6 หลัก (ลดขั้นต่ำเป็น 1 หลัก)
    if not data.get("house_no"):
        s_wo_age = re.sub(r"(?:อายุ\s*)?\d{1,3}\s*ปี", " ", s)
        # จับทั้งแบบมี/ไม่มี "บ้านเลขที่" แต่ต้องไม่ใช่เลขอายุ
        m_house = re.search(r"(?:บ้านเลขที่\s*)?(\d{1,6}(?:/\d{1,4})?)", s_wo_age)
        if m_house:
            data["house_no"] = m_house.group(1)

    # province สุดท้าย: ถ้ายังไม่มี ให้เดาจาก token ไทยสุดท้ายในข้อความ
    if not data.get("province"):
        thai_tokens = re.findall(r"[\u0E00-\u0E7F]+", s)
        if thai_tokens:
            last_token = thai_tokens[-1]
            # ตรวจสอบว่า token สุดท้ายเป็นจังหวัดหรือไม่
            if last_token in THAI_PROVINCES:
                data["province"] = last_token
            elif last_token in PROVINCE_ALIASES:
                data["province"] = PROVINCE_ALIASES[last_token]
            else:
                # ลองหาจังหวัดที่มีชื่อใกล้เคียง
                for province in THAI_PROVINCES:
                    if last_token in province or province.endswith(last_token):
                        data["province"] = province
                        break
                else:
                    data["province"] = last_token  # fallback

    return data


def parse_defendant_info(text: str) -> Dict:
    """Parse defendant information (person or company) from Thai text.
    Returns dict with keys: entity_type, name, address, phone, etc.
    """
    s = normalize_thai_digits((text or "").strip())
    
    # Determine if it's a company or person
    entity_type = "Person"  # default
    if re.search(r"บริษัท|จำกัด|มหาชน|ห้างหุ้นส่วน|องค์การ|สำนักงาน", s):
        entity_type = "Company"
    
    # Extract name
    name = None
    title = None
    
    if entity_type == "Company":
        # Company name patterns - extract from "บริษัท" keyword
        # First try: direct pattern "บริษัท xxx จำกัด"
        m_company = re.search(r"(บริษัท\s+[\u0E00-\u0E7F\s]+?จำกัด)", s)
        if m_company:
            name = m_company.group(1).strip()
        else:
            # Second try: find any "บริษัท" pattern before location
            m_company2 = re.search(r"(บริษัท\s+[^ตั้งอยู่โทร]+?)(?:\s*ตั้งอยู่|\s*อยู่|\s*โทร)", s)
            if m_company2:
                name = m_company2.group(1).strip()
            else:
                # Fallback: everything before address/phone
                parts = re.split(r"(ตั้งอยู่|อยู่|โทร)", s)
                if parts:
                    # Look for company name in the first part
                    first_part = parts[0]
                    m_fallback = re.search(r"(บริษัท\s+[\u0E00-\u0E7F\s]+)", first_part)
                    if m_fallback:
                        name = m_fallback.group(1).strip()
                    else:
                        name = first_part.strip()
    else:
        # Person name (similar to plaintiff parsing)
        m_title = re.search(r"(นาย|นางสาว|นาง|เด็กชาย|เด็กหญิง)", s)
        title = m_title.group(1) if m_title else "นาย"
        
        # Extract name parts after title
        name_zone = s
        if m_title:
            name_zone = s[m_title.end():].strip()
        
        # Split by address/phone keywords
        name_zone = re.split(r"(อยู่|ตั้งอยู่|โทร|บ้านเลขที่)", name_zone)[0].strip()
        
        # Get name parts
        name_parts = re.findall(r"[\u0E00-\u0E7F]+", name_zone)[:3]  # max 3 parts
        if name_parts:
            name = f"{title} {' '.join(name_parts)}"
    
    # Extract address components
    address_info = _extract_address_from_text(s)
    
    # Extract phone number
    phone = None
    m_phone = re.search(r"โทร\.?\s*([\d\-\s]+)", s)
    if m_phone:
        phone = re.sub(r"[\s\-]", "", m_phone.group(1))  # Clean phone number
    
    return {
        "entity_type": entity_type,
        "name": name,
        "title": title if entity_type == "Person" else None,
        "address": address_info.get("full_address"),
        "house_no": address_info.get("house_no"),
        "street": address_info.get("street"),
        "subdistrict": address_info.get("subdistrict"),
        "district": address_info.get("district"),
        "province": address_info.get("province"),
        "postal_code": address_info.get("postal_code"),
        "phone": phone,
    }


def _extract_address_from_text(text: str) -> Dict:
    """Extract address components from text."""
    s = normalize_thai_digits(text.strip())
    
    # House number and street
    house_no = None
    street = None
    
    # Pattern: "99/1 ถนนกาญจนวนิช"
    m_addr = re.search(r"(\d+(?:/\d+)?)\s*(ถนน[\u0E00-\u0E7F]+)?", s)
    if m_addr:
        house_no = m_addr.group(1)
        if m_addr.group(2):
            street = m_addr.group(2)
    
    # District (อำเภอ/เขต)
    district = None
    m_district = re.search(r"(?:อำเภอ|เขต|อ\.)\s*([\u0E00-\u0E7F]+)", s)
    if m_district:
        district = m_district.group(1)
    
    # Province
    province = None
    m_province = re.search(r"(?:จังหวัด|จ\.)\s*([\u0E00-\u0E7F]+)", s)
    if m_province:
        province = m_province.group(1)
    elif district:
        # Try to infer province from district + context
        thai_tokens = re.findall(r"[\u0E00-\u0E7F]+", s)
        for i, token in enumerate(thai_tokens):
            if token == district and i + 1 < len(thai_tokens):
                next_token = thai_tokens[i + 1]
                if next_token in THAI_PROVINCES:
                    province = next_token
                    break
    
    # Postal code
    postal_code = None
    m_postal = re.search(r"(\d{5})", s)
    if m_postal:
        postal_code = m_postal.group(1)
    
    # Construct full address
    addr_parts = []
    if house_no:
        addr_parts.append(house_no)
    if street:
        addr_parts.append(street)
    if district:
        addr_parts.append(f"อำเภอ{district}")
    if province:
        addr_parts.append(f"จังหวัด{province}")
    if postal_code:
        addr_parts.append(postal_code)
    
    full_address = " ".join(addr_parts) if addr_parts else None
    
    return {
        "full_address": full_address,
        "house_no": house_no,
        "street": street,
        "district": district,
        "province": province,
        "postal_code": postal_code,
    }


def upsert_defendant_to_graph(defendant_info: Dict, case_id: str):
    """Add defendant information to Neo4j graph and link to court case."""
    from ..services.neo4j_service import upsert_graph
    from ..models.graph import SimpleNode, SimpleRel, SimpleGraphDocument
    
    nodes = []
    relationships = []
    
    # Main defendant entity
    entity_type = defendant_info.get("entity_type", "Person")
    entity_name = defendant_info.get("name", "")
    
    if not entity_name:
        return
    
    # Create defendant node
    defendant_id = f"defendant_{entity_name}_{case_id}"
    defendant_node = SimpleNode(defendant_id, entity_type)
    nodes.append(defendant_node)
    
    # Create court case node
    case_node = SimpleNode(f"case_{case_id}", "CourtCase")
    nodes.append(case_node)
    
    # Link to court case
    relationships.append(SimpleRel(defendant_node, case_node, "DEFENDANT"))
    
    # Address components
    if defendant_info.get("house_no") or defendant_info.get("street"):
        addr_id = f"addr_{defendant_id}"
        addr_node = SimpleNode(addr_id, "Address")
        nodes.append(addr_node)
        
        # Link defendant to address
        rel_type = "LOCATED_AT" if entity_type == "Company" else "RESIDES_AT"
        relationships.append(SimpleRel(defendant_node, addr_node, rel_type))
        
        # Province/District/Postal connections
        if defendant_info.get("province"):
            prov_id = f"province_{defendant_info['province']}"
            prov_node = SimpleNode(prov_id, "Province")
            nodes.append(prov_node)
            relationships.append(SimpleRel(addr_node, prov_node, "IN_PROVINCE"))
        
        if defendant_info.get("district"):
            dist_id = f"district_{defendant_info['district']}"
            dist_node = SimpleNode(dist_id, "District")
            nodes.append(dist_node)
            relationships.append(SimpleRel(addr_node, dist_node, "IN_DISTRICT"))
        
        if defendant_info.get("postal_code"):
            postal_id = f"postal_{defendant_info['postal_code']}"
            postal_node = SimpleNode(postal_id, "PostalCode")
            nodes.append(postal_node)
            relationships.append(SimpleRel(addr_node, postal_node, "HAS_POSTAL_CODE"))
    
    # Phone number
    if defendant_info.get("phone"):
        phone_id = f"phone_{defendant_info['phone']}"
        phone_node = SimpleNode(phone_id, "PhoneNumber")
        nodes.append(phone_node)
        relationships.append(SimpleRel(defendant_node, phone_node, "HAS_PHONE"))
    
    # Upsert to Neo4j
    doc = SimpleGraphDocument(nodes=nodes, relationships=relationships)
    upsert_graph([doc], case_id)
    print(f"Added defendant {entity_name} to case {case_id}")


def parse_payment_period_and_termination(text: str) -> Dict:
    """Parse payment period and termination reason from text.
    
    Args:
        text: Input text in Thai
    
    Returns:
        Dict with payment period and termination reason
    """
    s = text.strip()
    
    # Parse payment period
    payment_period = "รายเดือน"  # Default
    
    # Check for daily payment indicators
    daily_indicators = [
        r"ค่าจ้างรายวัน",
        r"เงินวันละ",
        r"วันละ\s*\d+\s*บาท",
        r"ได้รับค่าจ้างรายวัน",
        r"จ่ายรายวัน"
    ]
    
    for pattern in daily_indicators:
        if re.search(pattern, s):
            payment_period = "รายวัน"
            break
    
    # Check for monthly payment indicators
    monthly_indicators = [
        r"ค่าจ้างรายเดือน",
        r"เงินเดือน",
        r"เดือนละ\s*\d+\s*บาท",
        r"ได้รับค่าจ้างรายเดือน",
        r"จ่ายรายเดือน"
    ]
    
    for pattern in monthly_indicators:
        if re.search(pattern, s):
            payment_period = "รายเดือน"
            break
    
    # Parse termination reason
    termination_reason = "เลิกจ้างโดยนายจ้าง"  # Default
    
    # Check for resignation
    resignation_patterns = [
        r"ลาออก",
        r"ออกจากงาน",
        r"ขอลาออก",
        r"ลาออกเอง"
    ]
    
    for pattern in resignation_patterns:
        if re.search(pattern, s):
            termination_reason = "ลาออกเอง"
            break
    
    # Check for serious misconduct termination
    misconduct_patterns = [
        r"เลิกจ้างเพราะผิดร้ายแรง",
        r"ผิดร้ายแรง",
        r"มาตรา\s*119",
        r"กระทำผิดร้ายแรง",
        r"ประพฤติผิด"
    ]
    
    for pattern in misconduct_patterns:
        if re.search(pattern, s):
            termination_reason = "เลิกจ้างเพราะผิดร้ายแรง"
            break
    
    # Check for immediate termination
    immediate_patterns = [
        r"เลิกจ้างทันที",
        r"ไล่ออกทันที",
        r"ไม่บอกล่วงหน้า",
        r"เลิกจ้างโดยไม่บอกกล่าวล่วงหน้า"
    ]
    
    for pattern in immediate_patterns:
        if re.search(pattern, s):
            if "ผิดร้ายแรง" not in termination_reason:
                termination_reason = "เลิกจ้างโดยนายจ้างโดยไม่บอกกล่าวล่วงหน้า"
            break
    
    return {
        "payment_period": payment_period,
        "termination_reason": termination_reason,
        "raw_text": s
    }


def parse_employment_info(text: str) -> Dict:
    """Parse employment information from Thai text.
    Returns dict with keys: start_date, position, daily_wage, years, months, total_days, etc.
    """
    s = normalize_thai_digits((text or "").strip())
    
    # Parse start date
    start_date = None
    start_date_iso = None
    
    # Pattern: "1 ม.ค. 60" or "1 มกราคม 2560"
    m_date = re.search(r"(\d{1,2})\s*(ม\.ค\.|มกราคม|ก\.พ\.|กุมภาพันธ์|มี\.ค\.|มีนาคม|เม\.ย\.|เมษายน|พ\.ค\.|พฤษภาคม|มิ\.ย\.|มิถุนายน|ก\.ค\.|กรกฎาคม|ส\.ค\.|สิงหาคม|ก\.ย\.|กันยายน|ต\.ค\.|ตุลาคม|พ\.ย\.|พฤศจิกายน|ธ\.ค\.|ธันวาคม)\s*(\d{2,4})", s)
    if m_date:
        day = int(m_date.group(1))
        month_str = m_date.group(2)
        year = int(m_date.group(3))
        
        # Convert short month to full month for THAI_MONTHS lookup
        month_mapping = {
            "ม.ค.": "มกราคม", "ก.พ.": "กุมภาพันธ์", "มี.ค.": "มีนาคม", "เม.ย.": "เมษายน",
            "พ.ค.": "พฤษภาคม", "มิ.ย.": "มิถุนายน", "ก.ค.": "กรกฎาคม", "ส.ค.": "สิงหาคม",
            "ก.ย.": "กันยายน", "ต.ค.": "ตุลาคม", "พ.ย.": "พฤศจิกายน", "ธ.ค.": "ธันวาคม"
        }
        
        full_month = month_mapping.get(month_str, month_str)
        month_num = THAI_MONTHS.get(full_month)
        
        if month_num:
            # Handle Buddhist year (convert to Gregorian if needed)
            if year < 100:  # 60 -> 2560
                year += 2500
            if year > 2400:  # Buddhist to Gregorian
                year -= 543
            
            start_date = f"{day} {full_month} {year + 543}"  # Keep Thai format for display
            start_date_iso = f"{year:04d}-{month_num:02d}-{day:02d}"
    
    # Parse position
    position = None
    m_pos = re.search(r"(?:ตำแหน่ง|เป็น)\s*([\u0E00-\u0E7F\s]+?)(?:\s|$|เงิน|ค่าจ้าง)", s)
    if m_pos:
        position = m_pos.group(1).strip()
    
    # Parse daily wage
    daily_wage = None
    m_wage = re.search(r"เงิน(?:วันละ|รายวัน)?\s*(\d+)\s*บาท", s)
    if not m_wage:
        m_wage = re.search(r"ค่าจ้าง(?:รายวัน)?(?:วันละ)?\s*(\d+)\s*บาท", s)
    if not m_wage:
        # Check for monthly salary (convert to daily)
        m_monthly = re.search(r"เงินเดือน\s*(\d+)\s*บาท", s)
        if not m_monthly:
            m_monthly = re.search(r"เดือนละ\s*(\d+)\s*บาท", s)
        if m_monthly:
            monthly_salary = int(m_monthly.group(1))
            daily_wage = monthly_salary / 30  # Convert to daily wage
    if m_wage:
        daily_wage = int(m_wage.group(1))
    
    # Parse working period (years and months)
    years = 0
    months = 0
    
    m_period = re.search(r"ทำ(?:งาน|มา)?\s*(\d+)\s*ปี(?:\s*(\d+)\s*เดือน)?", s)
    if m_period:
        years = int(m_period.group(1))
        if m_period.group(2):
            months = int(m_period.group(2))
    
    # Parse weekend/holiday information
    weekend_days = None
    weekend_pattern = None
    
    # Pattern: "หยุดอาทิตย์ละ X วัน" or "หยุดอาทิย์ละ X วัน"
    m_weekend = re.search(r"หยุด(?:อาทิตย์|อาทิย์)ละ\s*(\d+)\s*วัน", s)
    if m_weekend:
        weekend_days = int(m_weekend.group(1))
        if weekend_days == 1:
            weekend_pattern = "หยุดอาทิตย์ละ 1 วัน (6 วันทำงาน/สัปดาห์)"
        elif weekend_days == 2:
            weekend_pattern = "หยุดอาทิตย์ละ 2 วัน (5 วันทำงาน/สัปดาห์)"
        else:
            weekend_pattern = f"หยุดอาทิตย์ละ {weekend_days} วัน"
    
    # Calculate total working days (more accurate with weekend info)
    if weekend_days:
        # Calculate working days per week
        working_days_per_week = 7 - weekend_days
        # Calculate total weeks worked
        total_weeks = ((years * 52) + (months * 4.33))
        # Calculate actual working days
        total_working_days = int(total_weeks * working_days_per_week)
    else:
        # Default calculation (assume 6 days/week)
        total_working_days = (years * 365) + (months * 30)
    
    # Keep total_days for backward compatibility
    total_days = total_working_days
    
    # Parse payment period and termination info
    payment_info = parse_payment_period_and_termination(s)
    
    return {
        "start_date": start_date,
        "start_date_iso": start_date_iso,
        "position": position,
        "daily_wage": daily_wage,
        "years": years,
        "months": months,
        "total_days": total_days,
        "weekend_days": weekend_days,
        "weekend_pattern": weekend_pattern,
        "total_working_days": total_working_days,
        "payment_period": payment_info["payment_period"],
        "termination_reason": payment_info["termination_reason"],
        "raw_text": s
    }


def calculate_advance_notice_pay(daily_wage: float, payment_period: str = "รายเดือน", termination_reason: str = "เลิกจ้างโดยนายจ้าง") -> Dict:
    """Calculate advance notice pay according to Labor Protection Act Section 17.
    
    Args:
        daily_wage: Daily wage amount
        payment_period: Payment period ("รายวัน", "รายเดือน")
        termination_reason: Reason for termination
    
    Returns:
        Dict with advance notice pay calculation details
    """
    
    # Check if entitled to advance notice pay
    exempt_reasons = [
        "ลาออกเอง",
        "เลิกจ้างเพราะผิดร้ายแรง",
        "มาตรา 119",
        "ผิดร้ายแรง"
    ]
    
    is_exempt = any(reason in termination_reason for reason in exempt_reasons)
    
    if is_exempt:
        return {
            "daily_wage": daily_wage,
            "payment_period": payment_period,
            "termination_reason": termination_reason,
            "is_entitled": False,
            "advance_notice_pay": 0,
            "advance_notice_days": 0,
            "calculation_basis": "ไม่มีสิทธิได้รับค่าบอกกล่าวล่วงหน้า",
            "legal_reference": "มาตรา 17 พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑"
        }
    
    # Calculate advance notice pay based on payment period
    if payment_period == "รายวัน":
        # Daily payment: 1 payment period (assume 7 days for weekly payment)
        advance_notice_days = 7
        advance_notice_pay = daily_wage * advance_notice_days
        calculation_basis = "รายวัน: ต้องบอกล่วงหน้าอย่างน้อย 1 งวดการจ่าย (7 วัน)"
    elif payment_period == "รายเดือน":
        # Monthly payment: 1 month (assume 30 days)
        advance_notice_days = 30
        advance_notice_pay = daily_wage * advance_notice_days
        calculation_basis = "รายเดือน: ต้องบอกล่วงหน้าอย่างน้อย 1 เดือน (30 วัน)"
    else:
        # Default to monthly
        advance_notice_days = 30
        advance_notice_pay = daily_wage * advance_notice_days
        calculation_basis = "ไม่ระบุงวดการจ่าย: ใช้ค่าเริ่มต้น 1 เดือน (30 วัน)"
    
    return {
        "daily_wage": daily_wage,
        "payment_period": payment_period,
        "termination_reason": termination_reason,
        "is_entitled": True,
        "advance_notice_pay": advance_notice_pay,
        "advance_notice_days": advance_notice_days,
        "calculation_basis": calculation_basis,
        "legal_reference": "มาตรา 17 พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑"
    }


def calculate_severance_pay(daily_wage: float, years: int, months: int) -> Dict:
    """Calculate severance pay according to Labor Protection Act Section 118.
    
    Args:
        daily_wage: Daily wage in THB
        years: Years of continuous employment
        months: Additional months of employment
    
    Returns:
        Dict with severance pay calculation
    """
    # Convert total period to days (approximate)
    total_days = (years * 365) + (months * 30)
    
    # Determine severance pay days according to Section 118
    if total_days >= 120 and years < 1:
        # 120 days to 1 year: 30 days
        severance_days = 30
        category = "120 วัน - 1 ปี"
    elif years >= 1 and years < 3:
        # 1 year to 3 years: 90 days
        severance_days = 90
        category = "1 - 3 ปี"
    elif years >= 3 and years < 6:
        # 3 years to 6 years: 180 days
        severance_days = 180
        category = "3 - 6 ปี"
    elif years >= 6 and years < 10:
        # 6 years to 10 years: 240 days
        severance_days = 240
        category = "6 - 10 ปี"
    elif years >= 10 and years < 20:
        # 10 years to 20 years: 300 days
        severance_days = 300
        category = "10 - 20 ปี"
    elif years >= 20:
        # 20 years and above: 400 days
        severance_days = 400
        category = "20 ปีขึ้นไป"
    else:
        # Less than 120 days: no severance pay
        severance_days = 0
        category = "ไม่ถึง 120 วัน"
    
    severance_amount = daily_wage * severance_days
    
    return {
        "daily_wage": daily_wage,
        "years": years,
        "months": months,
        "total_days": total_days,
        "severance_days": severance_days,
        "severance_amount": round(severance_amount, 2),
        "category": category,
        "legal_reference": "มาตรา 118 พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑"
    }


def calculate_labor_law_interest(principal_amount: float, days_overdue: int) -> Dict:
    """Calculate interest and penalty according to Labor Protection Act Section 9.
    
    Args:
        principal_amount: The amount owed (in THB)
        days_overdue: Number of days overdue
    
    Returns:
        Dict with interest calculations
    """
    # Section 9 Paragraph 1: 15% interest per year
    annual_rate = 0.15
    daily_rate = annual_rate / 365
    interest = principal_amount * daily_rate * days_overdue
    
    # Section 9 Paragraph 2: 15% penalty every 7 days (if intentionally withheld)
    penalty_periods = days_overdue // 7
    penalty = principal_amount * 0.15 * penalty_periods
    
    total_amount = principal_amount + interest + penalty
    
    return {
        "principal": principal_amount,
        "days_overdue": days_overdue,
        "annual_interest_rate": annual_rate,
        "daily_interest_rate": daily_rate,
        "interest": round(interest, 2),
        "penalty_periods": penalty_periods,
        "penalty": round(penalty, 2),
        "total_amount": round(total_amount, 2),
        "legal_reference": "มาตรา 9 พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑"
    }


def format_employment_summary(employment_info: Dict, case_id: str = None) -> str:
    """Format employment information into a readable Thai summary."""
    parts = []
    
    if employment_info.get("start_date"):
        parts.append(f"โจทก์เข้าทำงานเมื่อวันที่ {employment_info['start_date']}")
    
    if employment_info.get("position"):
        parts.append(f"ตำแหน่ง{employment_info['position']}")
    
    if employment_info.get("daily_wage"):
        parts.append(f"ค่าจ้างรายวันวันละ {employment_info['daily_wage']:,} บาท")
    
    if employment_info.get("years") or employment_info.get("months"):
        period_parts = []
        if employment_info.get("years"):
            period_parts.append(f"{employment_info['years']} ปี")
        if employment_info.get("months"):
            period_parts.append(f"{employment_info['months']} เดือน")
        
        if period_parts:
            parts.append(f"ทำงานต่อเนื่องเป็นเวลา {' '.join(period_parts)}")
    
    # Add weekend/working schedule information
    if employment_info.get("weekend_pattern"):
        parts.append(employment_info["weekend_pattern"])
    
    return " ".join(parts)


def parse_termination_info(text: str) -> Dict:
    """Parse termination information and labor law violations from Thai text.
    
    Args:
        text: Input text in Thai about termination
    
    Returns:
        Dict with termination details and violations
    """
    s = normalize_thai_digits((text or "").strip())
    
    # Parse termination date
    termination_date = None
    termination_date_iso = None
    
    # Pattern: "ถูกเลิกจ้าง 15 พ.ค. 68" or "เลิกจ้างวันที่ 15 พ.ค. 68"
    date_patterns = [
        r"(?:ถูก)?เลิกจ้าง(?:วันที่)?\s*(\d+)\s*พ\.ค\.\s*(\d+)",
        r"(?:ถูก)?เลิกจ้าง(?:วันที่)?\s*(\d+)\s*พฤษภาคม\s*(\d+)",
        r"(?:ถูก)?เลิกจ้าง(?:วันที่)?\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)",
        r"วันที่\s*(\d+)\s*พ\.ค\.\s*(\d+).*เลิกจ้าง",
        r"วันที่\s*(\d+)\s*พฤษภาคม\s*(\d+).*เลิกจ้าง"
    ]
    
    for pattern in date_patterns:
        m_date = re.search(pattern, s)
        if m_date:
            day = int(m_date.group(1))
            year = int(m_date.group(2))
            
            # Convert Buddhist era to Christian era if needed
            if year < 100:  # Two digit year (68 -> 2568 -> 2025)
                buddhist_year = year + 2500
                christian_year = buddhist_year - 543
            elif year > 2000 and year < 2100:  # Already Christian era (2025)
                christian_year = year
                buddhist_year = year + 543
            else:  # Buddhist era (2568 -> 2025)
                buddhist_year = year
                christian_year = year - 543
            
            termination_date = f"{day} พฤษภาคม {buddhist_year}"
            termination_date_iso = f"{christian_year}-05-{day:02d}"
            break
    
    # Parse termination reason
    termination_reason = "ไม่ระบุ"
    reason_patterns = [
        (r"ปรับโครงสร้าง", "ปรับโครงสร้างองค์กร"),
        (r"ลดต้นทุน", "ลดต้นทุนการดำเนินงาน"),
        (r"ปิดกิจการ", "ปิดกิจการ"),
        (r"ย้ายฐานการผลิต", "ย้ายฐานการผลิต"),
        (r"เศรษฐกิจไม่ดี", "ปัญหาทางเศรษฐกิจ"),
        (r"ผิดร้ายแรง", "เลิกจ้างเพราะผิดร้ายแรง"),
        (r"ลาออก", "ลาออกเอง")
    ]
    
    for pattern, reason in reason_patterns:
        if re.search(pattern, s):
            termination_reason = reason
            break
    
    # Detect violations
    violations = []
    
    # Check for advance notice violation
    no_advance_notice = False
    advance_notice_patterns = [
        r"ไม่แจ้งล่วงหน้า",
        r"ไม่บอกกล่าวล่วงหน้า",
        r"ไม่ได้แจ้งล่วงหน้า",
        r"ไม่มีการบอกกล่าวล่วงหน้า",
        r"มิได้มีการบอกกล่าวล่วงหน้า"
    ]
    
    for pattern in advance_notice_patterns:
        if re.search(pattern, s):
            no_advance_notice = True
            violations.append({
                "type": "ไม่บอกกล่าวล่วงหน้า",
                "description": "ไม่มีการบอกกล่าวล่วงหน้าตามมาตรา 17",
                "legal_reference": "มาตรา 17 พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑",
                "violation_severity": "สูง"
            })
            break
    
    # Check for severance pay violation
    no_severance_pay = False
    severance_patterns = [
        r"ไม่ได้ค่าชดเชย",
        r"ไม่จ่ายค่าชดเชย",
        r"ไม่ได้รับค่าชดเชย",
        r"มิได้จ่ายค่าชดเชย"
    ]
    
    for pattern in severance_patterns:
        if re.search(pattern, s):
            no_severance_pay = True
            violations.append({
                "type": "ไม่จ่ายค่าชดเชย",
                "description": "ไม่จ่ายค่าชดเชยตามมาตรา 118",
                "legal_reference": "มาตรา 118 พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑",
                "violation_severity": "สูงมาก"
            })
            break
    
    # Generate legal summary
    legal_summary_parts = []
    
    if termination_date:
        legal_summary_parts.append(f"เมื่อวันที่ {termination_date} จำเลยเลิกจ้างโจทก์")
    
    if termination_reason != "ไม่ระบุ":
        legal_summary_parts.append(f"โดยอ้างเหตุ{termination_reason}")
    
    if violations:
        violation_descriptions = []
        for violation in violations:
            if violation["type"] == "ไม่บอกกล่าวล่วงหน้า":
                violation_descriptions.append("มิได้มีการบอกกล่าวล่วงหน้า")
            elif violation["type"] == "ไม่จ่ายค่าชดเชย":
                violation_descriptions.append("มิได้จ่ายค่าชดเชยตามกฎหมาย")
        
        if violation_descriptions:
            legal_summary_parts.append(" ".join(violation_descriptions))
    
    legal_summary = " ".join(legal_summary_parts)
    
    return {
        "termination_date": termination_date,
        "termination_date_iso": termination_date_iso,
        "termination_reason": termination_reason,
        "violations": violations,
        "no_advance_notice": no_advance_notice,
        "no_severance_pay": no_severance_pay,
        "legal_summary": legal_summary,
        "violation_count": len(violations),
        "raw_text": s
    }


def format_termination_summary(termination_info: Dict, case_id: str = None) -> str:
    """Format termination information into a readable Thai sentence."""
    
    parts = []
    
    if termination_info.get("termination_date"):
        parts.append(f"วันที่เลิกจ้าง: {termination_info['termination_date']}")
    
    if termination_info.get("termination_reason") and termination_info["termination_reason"] != "ไม่ระบุ":
        parts.append(f"เหตุผล: {termination_info['termination_reason']}")
    
    if termination_info.get("violations"):
        violation_list = [v["type"] for v in termination_info["violations"]]
        parts.append(f"การละเมิด: {', '.join(violation_list)}")
    
    if termination_info.get("legal_summary"):
        parts.append(f"สรุป: {termination_info['legal_summary']}")
    
    return " | ".join(parts)


def upsert_termination_to_graph(termination_info: Dict, case_id: str):
    """Add termination information to Neo4j graph and link to court case."""
    from ..services.neo4j_service import upsert_graph
    from ..models.graph import SimpleNode, SimpleRel, SimpleGraphDocument
    
    nodes = []
    relationships = []
    
    # Main termination event node
    termination_id = f"termination_event_{case_id}"
    termination_node = SimpleNode(termination_id, "TerminationEvent")
    nodes.append(termination_node)
    
    # Link to court case
    case_node = SimpleNode(case_id, "CourtCase")
    relationships.append(SimpleRel(case_node, termination_node, "TERMINATED_ON"))
    
    # Termination date node
    if termination_info.get("termination_date_iso"):
        date_id = f"termination_date_{termination_info['termination_date_iso']}_{case_id}"
        date_node = SimpleNode(date_id, "Date")
        nodes.append(date_node)
        relationships.append(SimpleRel(termination_node, date_node, "OCCURRED_ON"))
    
    # Termination reason node
    if termination_info.get("termination_reason"):
        reason_id = f"termination_reason_{termination_info['termination_reason'].replace(' ', '_')}_{case_id}"
        reason_node = SimpleNode(reason_id, "TerminationReason")
        nodes.append(reason_node)
        relationships.append(SimpleRel(termination_node, reason_node, "TERMINATED_FOR"))
    
    # Violation nodes
    for i, violation in enumerate(termination_info.get("violations", [])):
        violation_id = f"violation_{violation['type'].replace(' ', '_')}_{case_id}_{i}"
        violation_node = SimpleNode(violation_id, "LaborViolation")
        nodes.append(violation_node)
        relationships.append(SimpleRel(termination_node, violation_node, "VIOLATED_BY"))
        
        # Legal claim node for each violation
        claim_id = f"claim_{violation['type'].replace(' ', '_')}_{case_id}_{i}"
        claim_node = SimpleNode(claim_id, "LegalClaim")
        nodes.append(claim_node)
        relationships.append(SimpleRel(violation_node, claim_node, "RESULTS_IN"))
    
    # Store in Neo4j
    if nodes or relationships:
        doc = SimpleGraphDocument(nodes=nodes, relationships=relationships)
        upsert_graph([doc], case_id)
        print(f"Added termination info to case {case_id}")


def parse_court_claims(text: str) -> Dict:
    """Parse court claims and damages from Thai text.
    
    Args:
        text: Input text in Thai about claims
    
    Returns:
        Dict with court claims and formal request
    """
    s = text.strip()
    
    # Define claim types and their formal names
    claim_types = {
        "ค่าบอกกล่าวล่วงหน้า": {
            "formal_name": "ค่าบอกกล่าวล่วงหน้า",
            "legal_basis": "มาตรา 17 พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑",
            "category": "advance_notice_pay"
        },
        "ค่าชดเชย": {
            "formal_name": "ค่าชดเชยตามกฎหมาย",
            "legal_basis": "มาตรา 118 พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑",
            "category": "severance_pay"
        },
        "วันหยุดพักร้อน": {
            "formal_name": "ค่าจ้างสำหรับวันหยุดพักผ่อนประจำปี",
            "legal_basis": "มาตรา 30 พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑",
            "category": "vacation_pay"
        },
        "ค่าเสียหายจากเลิกจ้างไม่เป็นธรรม": {
            "formal_name": "ค่าเสียหายจากการเลิกจ้างไม่เป็นธรรม",
            "legal_basis": "มาตรา 49 พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑",
            "category": "unfair_dismissal_damages"
        }
    }
    
    # Additional patterns for claim detection
    claim_patterns = {
        "advance_notice_pay": [
            r"ค่าบอกกล่าวล่วงหน้า",
            r"บอกกล่าวล่วงหน้า",
            r"ค่าแจ้งล่วงหน้า"
        ],
        "severance_pay": [
            r"ค่าชดเชย",
            r"เงินชดเชย",
            r"ชดเชย"
        ],
        "vacation_pay": [
            r"วันหยุดพักร้อน",
            r"วันหยุดพักผ่อน",
            r"ค่าจ้างวันหยุด",
            r"พักผ่อนประจำปี"
        ],
        "unfair_dismissal_damages": [
            r"ค่าเสียหายจากเลิกจ้างไม่เป็นธรรม",
            r"เลิกจ้างไม่เป็นธรรม",
            r"ค่าเสียหาย.*เลิกจ้าง",
            r"การเลิกจ้างไม่เป็นธรรม"
        ]
    }
    
    # Detect claims from input text
    detected_claims = []
    
    for category, patterns in claim_patterns.items():
        for pattern in patterns:
            if re.search(pattern, s, re.IGNORECASE):
                # Find matching claim type
                for claim_key, claim_info in claim_types.items():
                    if claim_info["category"] == category:
                        detected_claims.append(claim_info)
                        break
                break
    
    # Generate formal court request
    if detected_claims:
        claim_names = [claim["formal_name"] for claim in detected_claims]
        
        if len(claim_names) == 1:
            formal_request = f"โจทก์ขอให้ศาลมีคำพิพากษาให้จำเลยชำระ {claim_names[0]}"
        elif len(claim_names) == 2:
            formal_request = f"โจทก์ขอให้ศาลมีคำพิพากษาให้จำเลยชำระ {claim_names[0]} และ{claim_names[1]}"
        else:
            # Multiple claims
            last_claim = claim_names[-1]
            other_claims = ", ".join(claim_names[:-1])
            formal_request = f"โจทก์ขอให้ศาลมีคำพิพากษาให้จำเลยชำระ {other_claims} และ{last_claim}"
    else:
        formal_request = "โจทก์ขอให้ศาลมีคำพิพากษาตามที่เห็นสมควร"
    
    return {
        "detected_claims": detected_claims,
        "claim_count": len(detected_claims),
        "formal_request": formal_request,
        "raw_text": s
    }


def format_court_claims_summary(claims_info: Dict, case_id: str = None) -> str:
    """Format court claims information into a readable Thai sentence."""
    
    if not claims_info.get("formal_request"):
        return "ไม่พบข้อมูลการเรียกร้อง"
    
    return claims_info["formal_request"]


def upsert_court_claims_to_graph(claims_info: Dict, case_id: str):
    """Add court claims information to Neo4j graph and link to court case."""
    from ..services.neo4j_service import upsert_graph
    from ..models.graph import SimpleNode, SimpleRel, SimpleGraphDocument
    
    nodes = []
    relationships = []
    
    # Main court request node
    request_id = f"court_request_{case_id}"
    request_node = SimpleNode(request_id, "CourtRequest")
    nodes.append(request_node)
    
    # Link to court case
    case_node = SimpleNode(case_id, "CourtCase")
    relationships.append(SimpleRel(case_node, request_node, "REQUESTS"))
    
    # Create nodes for each detected claim
    for i, claim in enumerate(claims_info.get("detected_claims", [])):
        category = claim["category"]
        
        if category == "advance_notice_pay":
            claim_id = f"advance_notice_claim_{case_id}"
            claim_node = SimpleNode(claim_id, "AdvanceNoticePay")
        elif category == "severance_pay":
            claim_id = f"severance_claim_{case_id}"
            claim_node = SimpleNode(claim_id, "SeverancePay")
        elif category == "vacation_pay":
            claim_id = f"vacation_pay_claim_{case_id}"
            claim_node = SimpleNode(claim_id, "VacationPay")
        elif category == "unfair_dismissal_damages":
            claim_id = f"unfair_dismissal_damages_{case_id}"
            claim_node = SimpleNode(claim_id, "Damages")
            nodes.append(claim_node)
            relationships.append(SimpleRel(request_node, claim_node, "CLAIMS"))
            
            # Create unfair dismissal node
            dismissal_id = f"unfair_dismissal_{case_id}"
            dismissal_node = SimpleNode(dismissal_id, "UnfairDismissal")
            nodes.append(dismissal_node)
            relationships.append(SimpleRel(claim_node, dismissal_node, "DUE_TO"))
            continue
        else:
            continue  # Skip unknown categories
            
        nodes.append(claim_node)
        relationships.append(SimpleRel(request_node, claim_node, "CLAIMS"))
    
    # Store in Neo4j
    if nodes or relationships:
        doc = SimpleGraphDocument(nodes=nodes, relationships=relationships)
        upsert_graph([doc], case_id)
        print(f"Added court claims to case {case_id}")


def upsert_employment_to_graph(employment_info: Dict, case_id: str):
    """Add employment information to Neo4j graph and link to court case."""
    from ..services.neo4j_service import upsert_graph
    from ..models.graph import SimpleNode, SimpleRel, SimpleGraphDocument
    
    nodes = []
    relationships = []
    
    # Employment contract node
    contract_id = f"employment_{case_id}"
    contract_node = SimpleNode(contract_id, "EmploymentContract")
    nodes.append(contract_node)
    
    # Link to court case
    case_node = SimpleNode(f"case_{case_id}", "CourtCase")
    nodes.append(case_node)
    relationships.append(SimpleRel(contract_node, case_node, "RELATES_TO"))
    
    # Position node
    if employment_info.get("position"):
        pos_id = f"position_{employment_info['position']}_{case_id}"
        pos_node = SimpleNode(pos_id, "Position")
        nodes.append(pos_node)
        relationships.append(SimpleRel(contract_node, pos_node, "HAS_POSITION"))
    
    # Salary node
    if employment_info.get("daily_wage"):
        salary_id = f"salary_{employment_info['daily_wage']}_{case_id}"
        salary_node = SimpleNode(salary_id, "Salary")
        nodes.append(salary_node)
        relationships.append(SimpleRel(contract_node, salary_node, "HAS_SALARY"))
    
    # Employment period node
    if employment_info.get("years") or employment_info.get("months"):
        period_id = f"period_{employment_info.get('years', 0)}y_{employment_info.get('months', 0)}m_{case_id}"
        period_node = SimpleNode(period_id, "EmploymentPeriod")
        nodes.append(period_node)
        relationships.append(SimpleRel(contract_node, period_node, "HAS_PERIOD"))
        
        # Working days node
        if employment_info.get("total_days"):
            days_id = f"days_{employment_info['total_days']}_{case_id}"
            days_node = SimpleNode(days_id, "WorkingDays")
            nodes.append(days_node)
            relationships.append(SimpleRel(period_node, days_node, "WORKED_DAYS"))
        
        # Severance pay node (if applicable)
        if employment_info.get("years") is not None and employment_info.get("daily_wage"):
            severance_info = calculate_severance_pay(
                employment_info["daily_wage"], 
                employment_info.get("years", 0), 
                employment_info.get("months", 0)
            )
            if severance_info["severance_days"] > 0:
                severance_id = f"severance_{severance_info['severance_days']}days_{case_id}"
                severance_node = SimpleNode(severance_id, "SeverancePay")
                nodes.append(severance_node)
                relationships.append(SimpleRel(period_node, severance_node, "ENTITLED_TO"))
    
    # Working schedule node (if weekend info available)
    if employment_info.get("weekend_days") is not None:
        schedule_id = f"schedule_{employment_info['weekend_days']}weekend_{case_id}"
        schedule_node = SimpleNode(schedule_id, "WorkingSchedule")
        nodes.append(schedule_node)
        relationships.append(SimpleRel(contract_node, schedule_node, "HAS_SCHEDULE"))
        
        # Weekend days node
        weekend_id = f"weekend_{employment_info['weekend_days']}days_{case_id}"
        weekend_node = SimpleNode(weekend_id, "WeekendDays")
        nodes.append(weekend_node)
        relationships.append(SimpleRel(schedule_node, weekend_node, "HAS_WEEKEND"))
    
    # Payment period node
    if employment_info.get("payment_period"):
        period_id = f"payment_{employment_info['payment_period']}_{case_id}"
        payment_period_node = SimpleNode(period_id, "PaymentPeriod")
        nodes.append(payment_period_node)
        relationships.append(SimpleRel(contract_node, payment_period_node, "HAS_PAYMENT_PERIOD"))
    
    # Termination reason node
    if employment_info.get("termination_reason"):
        reason_id = f"termination_{employment_info['termination_reason'].replace(' ', '_')}_{case_id}"
        termination_node = SimpleNode(reason_id, "TerminationReason")
        nodes.append(termination_node)
        relationships.append(SimpleRel(contract_node, termination_node, "TERMINATED_FOR"))
    
    # Advance notice pay node (if applicable)
    if employment_info.get("daily_wage") and employment_info.get("payment_period"):
        advance_notice_info = calculate_advance_notice_pay(
            employment_info["daily_wage"],
            employment_info["payment_period"],
            employment_info.get("termination_reason", "เลิกจ้างโดยนายจ้าง")
        )
        
        if advance_notice_info["is_entitled"]:
            notice_id = f"advance_notice_{advance_notice_info['advance_notice_days']}days_{case_id}"
            notice_node = SimpleNode(notice_id, "AdvanceNoticePay")
            nodes.append(notice_node)
            relationships.append(SimpleRel(contract_node, notice_node, "REQUIRES_NOTICE"))
    
    # Start date node
    if employment_info.get("start_date_iso"):
        date_id = f"start_date_{employment_info['start_date_iso']}_{case_id}"
        date_node = SimpleNode(date_id, "Date")
        nodes.append(date_node)
        relationships.append(SimpleRel(contract_node, date_node, "OCCURRED_ON"))
    
    # Upsert to Neo4j
    doc = SimpleGraphDocument(nodes=nodes, relationships=relationships)
    upsert_graph([doc], case_id)
    print(f"Added employment info to case {case_id}")


def upsert_thai_provinces():
    """Add all Thai provinces to Neo4j graph."""
    from ..services.neo4j_service import upsert_graph
    from ..models.graph import SimpleNode, SimpleRel, SimpleGraphDocument
    
    nodes = []
    for province in THAI_PROVINCES:
        nodes.append(SimpleNode(f"province_{province}", "Province"))
    
    doc = SimpleGraphDocument(nodes=nodes, relationships=[])
    upsert_graph([doc], "provinces_setup")
    print(f"Added {len(THAI_PROVINCES)} Thai provinces to Neo4j")
