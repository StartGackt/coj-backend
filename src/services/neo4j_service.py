"""Neo4j database operations service"""

import re
from typing import List, Dict, Optional, Tuple
from neo4j import GraphDatabase

from ..config import NEO4J_URI, NEO4J_AUTH, NEO4J_DATABASE, ALLOWED_NODE_LABELS
from ..models.graph import SimpleNode, SimpleRel, SimpleGraphDocument
from ..utils.thai_parser import sanitize_label, sanitize_rel_type, normalize_thai_digits


def setup_constraints():
    """Create uniqueness constraints in Neo4j"""
    stmts = [
        "CREATE CONSTRAINT uniq_person_name IF NOT EXISTS FOR (n:Person) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_company_name IF NOT EXISTS FOR (n:Company) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_legalrole_value IF NOT EXISTS FOR (n:LegalRole) REQUIRE n.value IS UNIQUE",
        "CREATE CONSTRAINT uniq_courtcase_caseid IF NOT EXISTS FOR (n:CourtCase) REQUIRE n.caseId IS UNIQUE",
        "CREATE CONSTRAINT uniq_group_name IF NOT EXISTS FOR (n:Group) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_section_name IF NOT EXISTS FOR (n:Section) REQUIRE n.name IS UNIQUE",
        # Expanded legal structure
        "CREATE CONSTRAINT uniq_act_name IF NOT EXISTS FOR (n:Act) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_book_name IF NOT EXISTS FOR (n:Book) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_title_name IF NOT EXISTS FOR (n:Title) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_chapter_name IF NOT EXISTS FOR (n:Chapter) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_part_name IF NOT EXISTS FOR (n:Part) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_section_desc_name IF NOT EXISTS FOR (n:Section_desc) REQUIRE n.name IS UNIQUE",
        # Enforcement additions
        "CREATE CONSTRAINT uniq_paragraph_name IF NOT EXISTS FOR (n:Paragraph) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_interest_rate_name IF NOT EXISTS FOR (n:InterestRate) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_penalty_name IF NOT EXISTS FOR (n:Penalty) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_timeperiod_name IF NOT EXISTS FOR (n:TimePeriod) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_cause_name IF NOT EXISTS FOR (n:Cause) REQUIRE n.name IS UNIQUE",
        # Addressing
        "CREATE CONSTRAINT uniq_address_id IF NOT EXISTS FOR (n:Address) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_province_name IF NOT EXISTS FOR (n:Province) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_district_name IF NOT EXISTS FOR (n:District) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_subdistrict_name IF NOT EXISTS FOR (n:Subdistrict) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT uniq_postal_code IF NOT EXISTS FOR (n:PostalCode) REQUIRE n.code IS UNIQUE",
        "CREATE CONSTRAINT uniq_phone_number IF NOT EXISTS FOR (n:PhoneNumber) REQUIRE n.number IS UNIQUE",
        # Employment constraints
        "CREATE CONSTRAINT uniq_employment_period IF NOT EXISTS FOR (n:EmploymentPeriod) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT uniq_salary IF NOT EXISTS FOR (n:Salary) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT uniq_working_days IF NOT EXISTS FOR (n:WorkingDays) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT uniq_severance_pay IF NOT EXISTS FOR (n:SeverancePay) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT uniq_working_schedule IF NOT EXISTS FOR (n:WorkingSchedule) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT uniq_weekend_days IF NOT EXISTS FOR (n:WeekendDays) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT uniq_advance_notice_pay IF NOT EXISTS FOR (n:AdvanceNoticePay) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT uniq_payment_period IF NOT EXISTS FOR (n:PaymentPeriod) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT uniq_termination_reason IF NOT EXISTS FOR (n:TerminationReason) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT uniq_termination_event IF NOT EXISTS FOR (n:TerminationEvent) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT uniq_labor_violation IF NOT EXISTS FOR (n:LaborViolation) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT uniq_legal_claim IF NOT EXISTS FOR (n:LegalClaim) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT uniq_court_request IF NOT EXISTS FOR (n:CourtRequest) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT uniq_damages IF NOT EXISTS FOR (n:Damages) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT uniq_vacation_pay IF NOT EXISTS FOR (n:VacationPay) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT uniq_unfair_dismissal IF NOT EXISTS FOR (n:UnfairDismissal) REQUIRE n.id IS UNIQUE",
    ]
    
    with GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH) as driver:
        with driver.session(database=NEO4J_DATABASE) as session:
            for q in stmts:
                try:
                    session.run(q)
                except Exception as e:
                    print(f"Constraint warn: {e}")


def map_node(node: SimpleNode) -> Tuple[str, Dict]:
    """Map a SimpleNode to Neo4j label and properties"""
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


def upsert_graph(graph_docs: List[SimpleGraphDocument], case_id: str):
    """Upsert graph documents to Neo4j"""
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

    with GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH) as driver:
        with driver.session(database=NEO4J_DATABASE) as session:
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


def index_doc_chunks(text_chunks: List[str], case_id: str):
    """Index document chunks in Neo4j for vector store metadata"""
    with GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH) as driver:
        with driver.session(database=NEO4J_DATABASE) as session:
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
                    section=sec,
                )


def fetch_doc_chunks(case_id: Optional[str] = None) -> List[dict]:
    """Fetch document chunks from Neo4j"""
    with GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH) as driver:
        with driver.session(database=NEO4J_DATABASE) as session:
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


def graph_retrieve(case_id: Optional[str] = None, limit: int = 20) -> List[dict]:
    """Retrieve graph facts from Neo4j"""
    with GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH) as driver:
        with driver.session() as session:
            if case_id:
                # 1) Original facts
                q_facts = """
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
                facts_res = session.run(q_facts, cid=case_id, limit=limit)
                facts = [r.data() for r in facts_res]

                # 2) Plaintiff + Address (append to facts)
                q_plaintiff = """
                MATCH (c:CourtCase {caseId: $cid})
                OPTIONAL MATCH (p:Person)-[:PARTY]->(c)
                OPTIONAL MATCH (p)-[:HAS_ROLE]->(role:LegalRole)
                OPTIONAL MATCH (p)-[:RESIDES_AT]->(addr:Address)
                OPTIONAL MATCH (addr)-[:IN_SUBDISTRICT]->(sd:Subdistrict)
                OPTIONAL MATCH (addr)-[:IN_DISTRICT]->(dist:District)
                OPTIONAL MATCH (addr)-[:IN_PROVINCE]->(prov:Province)
                OPTIONAL MATCH (addr)-[:HAS_POSTAL_CODE]->(pc:PostalCode)
                WHERE p IS NOT NULL AND (role.value = 'Plaintiff' OR role.value IS NULL)
                RETURN DISTINCT 
                    p.name AS person, role.value AS role, c.caseId AS caseId,
                    NULL AS date, NULL AS amount,
                    NULL AS section, NULL AS section_desc,
                    addr.name AS address, sd.name AS subdistrict, dist.name AS district, prov.name AS province, pc.code AS postal_code
                LIMIT 1
                """
                pl_res = session.run(q_plaintiff, cid=case_id)
                facts.extend([r.data() for r in pl_res])
                return facts
            else:
                # No case specified: keep original behavior for simplicity
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
