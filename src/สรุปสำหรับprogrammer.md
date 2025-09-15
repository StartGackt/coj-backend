# สรุปสำหรับ Programmer (Architecture Deep Dive)

เอกสารนี้อธิบายภาพรวมสถาปัตยกรรม การไหลของข้อมูล องค์ประกอบหลัก วิธีค้นหาแบบ Hybrid (Vector + TF‑IDF + KG) สคีมา Neo4j และแนวทางต่อยอด เพื่อให้นักพัฒนาคนใหม่รับช่วงต่อได้ทันที

## ภาพรวมสถาปัตยกรรม

```text
+------------------+            +---------------------------+            +------------------------+
|  Next.js (App)   |  /api/*    |  Next API Route (Proxy)   |  HTTP/JSON |  FastAPI (Backend API) |
|  pages/components+----------->|  app/api/court-documents  +----------->|  src/api/routes.py     |
|  petition-form   |            |  route.ts                 |            |  + services/*          |
+------------------+            +---------------------------+            +-----------+------------+
                                                                                   |
                                                                                   | Neo4j Driver
                                                                                   v
                                                                        +----------+-----------+
                                                                        |       Neo4j DB      |
                                                                        |  (Knowledge Graph)  |
                                                                        +----------+----------+
                                                                                   ^
                                                                                   | facts/chunks
                                                                                   |
  (Optional for vector)                                                            |
   OpenAI Embeddings  <------------------------------------------------------------+
```

- Frontend (Next.js): ฟอร์มยื่นคำร้องแรงงาน (`components/petition-form.tsx`) เรียก `/api/court-documents?q=...`
- Next API Route: proxy ไป `BACKEND_URL/court-documents/search`
- Backend (FastAPI): ใช้ Hybrid Search ผสม Vector Embeddings + TF‑IDF + Knowledge Graph (Neo4j)
- Neo4j: เก็บโหนด/ความสัมพันธ์ (KG) และ `DocChunk` สำหรับสืบค้น

## ลำดับเหตุการณ์ (Step 1 Suggestion)

```text
User types (เช่น "เลิกจ้างไม่เป็นธรรม")
  -> Frontend debounce 350ms เรียก /api/court-documents?q=...
    -> Next API proxy ไป BACKEND /court-documents/search
      -> routes.py: เรียก services.search.hybrid_search(q, case_id)
         -> ดึง DocChunk + สร้างคะแนน TF‑IDF
         -> ถ้ามี OPENAI_API_KEY: คำนวณ embeddings (query + docs) แล้วหา cosine similarity
         -> รวมคะแนน: 0.7*vector + 0.3*tfidf (ถ้าไม่มี vector ใช้ tfidf อย่างเดียว)
         -> ดึง facts จากกราฟ (graph_retrieve)
      -> routes.py: แมปผล + heuristic เป็นคำแนะนำเอกสารศาล (เช่น "คำฟ้องคดีแรงงาน รง1 / ศาลแรงงานกลาง")
      -> ส่ง JSON ให้ Frontend
  -> Frontend แสดงคำแนะนำใต้ textarea และ validation แบบเรียลไทม์
```

## ไฟล์หลัก และหน้าที่

- `app/api/court-documents/route.ts` (Next API): Proxy ไป Backend โดยอ่าน `BACKEND_URL`
- `components/petition-form.tsx` (UI):
  - Step 1 เริ่มค่าว่าง, debounce fetch, render คำแนะนำ AI ใต้กล่อง, ปุ่ม "ใช้คำแนะนำ"
  - Validation: ต้องมีทั้ง "ประเภทเอกสาร" (คำฟ้อง/คำร้อง/รง1) และ "ศาล" (ศาลแรงงานกลาง) จึงกดถัดไปได้
- `backend/NEO4j/run_api.py`: รัน FastAPI ที่ `0.0.0.0:8000`
- `backend/NEO4j/src/api/routes.py`:
  - `POST /ingest`: รับ texts → `extraction.rule_based_extract` → `neo4j_service.upsert_graph` + `index_doc_chunks`
  - `GET /search`: เรียก `search.hybrid_search` คืนเอกสารใกล้เคียง + facts
  - `GET /answer`, `POST /ask`: สร้างคำตอบแบบสรุปด้วย `search.synthesize_answer`
  - `GET /court-documents/search`: ใช้ Hybrid + heuristic เพื่อแนะนำชื่อเอกสารศาล (fallback fuzzy)
- `backend/NEO4j/src/services/extraction.py`: กติกาดึงเอนทิตี/ความสัมพันธ์จากข้อความไทย (Rule-based)
- `backend/NEO4j/src/services/neo4j_service.py`: ฟังก์ชันเชื่อม Neo4j (constraints, upsert, query facts/chunks)
- `backend/NEO4j/src/services/search.py`: Hybrid Search (Vector + TF‑IDF) + รวมผลกับ KG facts
- `backend/NEO4j/src/config.py`: ค่าตั้งค่า (Neo4j URI/USER/PASS, labels/relations, vocab size)

## Knowledge Graph Schema (ย่อ)

```text
(Person)-[:HAS_ROLE]->(LegalRole)
(Person)-[:PARTY]->(CourtCase)
(Person)-[:EMPLOYED_BY]->(EmploymentContract)
(CourtCase)-[:HAS_AMOUNT]->(MoneyAmount)
(CourtCase)-[:OCCURRED_ON]->(Date)
(Section)-[:HAS_DESC]->(Section_desc)
(Section)-[:SECTION]->(Group)
(CourtCase) --(metadata/docs)--> (DocChunk {caseId, chunkId, text, page, section})
```

- โหนดหลัก: `Person`, `CourtCase`, `LegalRole`, `MoneyAmount`, `Date`, `Section`, `Group`, `DocChunk`
- ความสัมพันธ์ช่วยตอบคำถามเชิงโครงสร้าง (คู่ความ, วันที่, จำนวนเงิน, มาตรา ฯลฯ)

## Hybrid Search ลึกขึ้น

- TF‑IDF (คีย์เวิร์ดตรง): `build_tfidf`, `vectorize_query`, `cosine`
- Vector (ความหมาย): `_embed_texts`, `_embed_query` ใช้ `OpenAIEmbeddings(model="text-embedding-3-small")` เมื่อมี `OPENAI_API_KEY`
- การรวมคะแนน: `score = 0.7*vector + 0.3*tfidf` (ถ้าไม่มีเวกเตอร์ ใช้ TF‑IDF อย่างเดียว)
- ผลลัพธ์: `top_docs` + `facts` → นำไปแมปเป็นคำแนะนำเอกสารศาลใน `routes.py`

เหตุผลการออกแบบ:

- เวกเตอร์ช่วยเดาความหมายเมื่อพิมพ์ไม่ตรง/คำพ้อง, TF‑IDF ช่วยยึดคีย์เวิร์ดเฉพาะ และ KG facts ช่วยตรวจสอบ/อธิบาย

## Endpoint สำคัญ (รูปแบบย่อ)

- `POST /ingest`
  - body: `{ texts: string[], case_id?: string }`
  - งาน: สร้าง/อัปเดต KG + index `DocChunk`
- `GET /court-documents/search`
  - query: `q`, `case_id?`, `k?`
  - คืน: `{ query, case_id, results: [{ id,title,description,court,score }], total }`
- `GET /search`
  - query: `q`, `case_id?`, `k?`
  - คืน: `{ query, case_id, top_docs: [...], facts: [...] }`
- `GET /answer`
  - query: `q`, `case_id?`, `k?`
  - คืน: คำตอบสังเคราะห์ + อ้างอิงเอกสาร/ข้อเท็จจริง

## การตั้งค่า (Environment)

- Frontend: `.env` → `BACKEND_URL=http://localhost:8000`
- Backend: `backend/NEO4j/src/config.py` อ่านจาก env
  - `NEO4J_URI` (default `bolt://localhost:7687`)
  - `NEO4J_USER` / `NEO4J_PASSWORD` / `NEO4J_DATABASE`
  - (ทางเลือก) `OPENAI_API_KEY` สำหรับ embeddings

## การรันและทดสอบ

- รัน Neo4j ให้เชื่อมต่อได้
- รัน Backend
  ```bash
  python backend/NEO4j/run_api.py
  ```
- ทดสอบ Hybrid Suggestion
  ```bash
  curl 'http://localhost:8000/court-documents/search?q=เลิกจ้างไม่เป็นธรรม'
  ```
- ฟรอนต์จะเรียกผ่าน proxy: `/api/court-documents?q=...`

## แนวทางต่อยอด (สำหรับน้องที่จะมาทำต่อ)

1. ทำให้ Vector Search เร็วขึ้น/แม่นขึ้น
   - สร้างดัชนีเวกเตอร์จริง (Neo4j vector index หรือ Qdrant – มีไลบรารีพร้อมใน `pyproject.toml`)
   - เก็บ embeddings ของ `DocChunk` ล่วงหน้า (batch job) แล้วใช้ ANN ค้นหา
2. ปรับปรุง Extraction
   - เพิ่มกฎใน `extraction.py` หรือเพิ่ม NER/LLM เพื่อดึงชื่อบุคคล/องค์กร/จำนวนเงิน/วันที่ให้แม่นยำขึ้น
3. ขยายเทมเพลตเอกสารศาล + Heuristic
   - เพิ่ม mapping คำค้น → เอกสาร/ศาล/ฟอร์ม, และรับ case_id เฉพาะเรื่องเพื่อความแม่นยำ
4. Observability/Debug
   - เพิ่ม log/trace, endpoint สำหรับ debug KG, และหน้า visualize กราฟ
5. ความปลอดภัย/สิทธิ์
   - เพิ่ม CORS/Rate limit/Auth ตามบริบทระบบจริง

## Checklist สำหรับ Developer ใหม่

- [ ] ติดตั้ง/เชื่อมต่อ Neo4j ได้ (ลอง `GET /Health` และลอง query กราฟใน Neo4j Browser)
- [ ] ตั้งค่า `BACKEND_URL` ใน Frontend และลอง `GET /court-documents/search`
- [ ] ทดสอบ `POST /ingest` ด้วยตัวอย่างข้อความไทย → ตรวจใน Neo4j ว่าโหนด/ความสัมพันธ์มาแล้ว
- [ ] (ถ้ามีคีย์) ตั้ง `OPENAI_API_KEY` แล้วลองสังเกตผล vector ช่วยดีขึ้นหรือไม่
- [ ] อ่านโค้ดใน `search.hybrid_search` และ `routes.search_court_documents` เพื่อเข้าใจ flow จริง

---

ถ้าติดตรงไหน ให้เริ่มไล่จาก API → services → Neo4j browser จะช่วยมองภาพรวมได้เร็วที่สุด
