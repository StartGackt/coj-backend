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
