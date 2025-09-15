"""Configuration and constants for Neo Legal KG"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Neo4j configuration
# Use bolt scheme by default for single-instance servers to avoid routing errors
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
NEO4J_AUTH = (NEO4J_USER, NEO4J_PASSWORD)

# Ontology / Schema
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
