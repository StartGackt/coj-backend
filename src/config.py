"""Configuration and constants for Neo Legal KG"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Neo4j configuration
# Use bolt scheme by default for single-instance servers to avoid routing errors
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "12345678")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
NEO4J_AUTH = (NEO4J_USER, NEO4J_PASSWORD)

# Ontology / Schema
ALLOWED_NODE_LABELS = [
    # Parties / case
    "Person",
    "Company",      # บริษัท/นิติบุคคล
    "CourtCase",
    # Employment domain
    "EmploymentContract",
    "Position",
    # Facts
    "MoneyAmount",
    "Date",
    # Legal meta
    "LegalRole",
    "LegalTerm",
    # Document structure (expanded to cover Thai law hierarchy)
    "Act",          # พระราชบัญญัติ / ประมวล
    "Book",         # ลักษณะ
    "Title",        # บท
    "Chapter",      # หมวด
    "Part",         # ตอน
    "Group",        # กลุ่ม (เดิม)
    "Section",      # มาตรา
    "Section_desc", # เนื้อหามาตรา
    # Enforcements
    "Paragraph",    # วรรคที่ x
    "InterestRate", # ดอกเบี้ยร้อยละ x ต่อปี/เดือน
    "Penalty",      # เงินเพิ่ม/เบี้ยปรับ
    "TimePeriod",   # ช่วงเวลา เช่น 7 วัน
    "Cause",        # เหตุ/เงื่อนไขการคิดดอกเบี้ย/เงินเพิ่ม
    # Addressing
    "Address",
    "Province",
    "District",
    "Subdistrict",
    "PostalCode",
    "PhoneNumber",  # เบอร์โทรศัพท์
    # Generic
    "Entity",
]

ALLOWED_REL_TYPES = [
    # Case / parties
    "PARTY",        # (Person|Company)-[:PARTY]->(CourtCase)
    "DEFENDANT",    # (Person|Company)-[:DEFENDANT]->(CourtCase)
    "HAS_ROLE",     # (Person)-[:HAS_ROLE]->(LegalRole)
    "CLAIMS",       # (Person)-[:CLAIMS]->(CourtCase)
    # Employment
    "EMPLOYED_BY",  # (Person)-[:EMPLOYED_BY]->(EmploymentContract|Organization|Person)
    # Facts
    "HAS_AMOUNT",   # (* )-[:HAS_AMOUNT]->(MoneyAmount)
    "OCCURRED_ON",  # (* )-[:OCCURRED_ON]->(Date)
    # Law structure hierarchy
    "BELONGS_TO",   # (Section)->(Chapter)->(Title)->(Book)->(Act)
    "HAS_DESC",     # (Section)-[:HAS_DESC]->(Section_desc)
    "HAS_PARAGRAPH",# (Section)-[:HAS_PARAGRAPH]->(Paragraph)
    "HAS_RATE",     # (Paragraph|Section)-[:HAS_RATE]->(InterestRate)
    "HAS_PENALTY",  # (Paragraph|Section)-[:HAS_PENALTY]->(Penalty)
    "WITHIN",       # (Penalty)-[:WITHIN]->(TimePeriod)
    "HAS_CAUSE",    # (Paragraph|Section)-[:HAS_CAUSE]->(Cause)
    "REFERS_TO",    # (Section)-[:REFERS_TO]->(Section)
    # Addressing
    "RESIDES_AT",   # (Person)-[:RESIDES_AT]->(Address)
    "LOCATED_AT",   # (Company)-[:LOCATED_AT]->(Address)
    "HAS_PHONE",    # (Person|Company)-[:HAS_PHONE]->(PhoneNumber)
    "IN_PROVINCE",  # (Address|District|Subdistrict)-[:IN_PROVINCE]->(Province)
    "IN_DISTRICT",  # (Address|Subdistrict)-[:IN_DISTRICT]->(District)
    "IN_SUBDISTRICT",# (Address)-[:IN_SUBDISTRICT]->(Subdistrict)
    "HAS_POSTAL_CODE", # (Address)-[:HAS_POSTAL_CODE]->(PostalCode)
    # Backward-compatible
    "SECTION",      # (Section)-[:SECTION]->(Group)
]

# Thai months mapping
THAI_MONTHS = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4,
    "พฤษภาคม": 5, "มิถุนายน": 6, "กรกฎาคม": 7, "สิงหาคม": 8,
    "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
}

# Thai digits mapping
THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

# TF-IDF configuration
MAX_VOCAB_SIZE = 2048

# API configuration
API_TITLE = "Neo Legal KG API"
API_DESCRIPTION = "Thai legal KG with rule-based extraction and hybrid search"
API_VERSION = "0.1.0"
