# SA Overview: ระบบยื่นคำร้องแรงงานด้วย Knowledge Graph + Hybrid Search

เอกสารนี้อธิบายสถาปัตยกรรมแบบเข้าใจง่ายสำหรับ System/Solution Architect: องค์ประกอบหลัก การไหลของข้อมูล แนวทางสเกล ความปลอดภัย และการดีพลอย

## ภาพรวมสถาปัตยกรรม (High-level)

```text
[ Web App (Next.js) ] --/api--> [ Next API Route (Proxy) ] --HTTP--> [ FastAPI Backend ] --(Bolt/HTTP)--> [ Neo4j ]
                                                        \--(Embeddings, optional)--> [ OpenAI ]
```

- Web App (Next.js): ฟอร์มผู้ใช้ กดพิมพ์/ค้นหา/แนะนำเอกสาร
- Next API Route: เป็น proxy ภายใน Next.js เพื่อติดต่อ Backend และซ่อนค่า BACKEND_URL
- FastAPI Backend: ให้บริการ ingest/search/answer/suggestions โดยใช้ Hybrid Search (Vector + TF‑IDF) และอ่าน facts จาก KG
- Neo4j (Knowledge Graph): เก็บโครงสร้างความรู้ (โจทก์/จำเลย/จำนวนเงิน/วันที่/มาตรา ฯลฯ) และชิ้นข้อความ DocChunk
- OpenAI (เลือกใช้): สร้างเวกเตอร์ความหมายของข้อความเพื่อค้นหาแบบ semantic

## ฟังก์ชันหลักและเส้นทางข้อมูล (Core Flows)

1. Ingest เอกสาร (ทำครั้งคราว/ตามไฟล์ใหม่)

   - Frontend ส่ง texts → FastAPI `/ingest`
   - Backend ทำ rule‑based extraction → สร้างโหนด/ความสัมพันธ์ → อัปเสิร์ท Neo4j → เก็บ DocChunk

2. คำแนะนำ Step 1 (แนะนำหัวข้อเอกสารศาลแบบเรียลไทม์)

   - ผู้ใช้พิมพ์คำ เช่น “เลิกจ้างไม่เป็นธรรม” → Frontend เรียก `/api/court-documents?q=...`
   - Proxy ไป Backend `/court-documents/search` → เรียก Hybrid Search → ผสม vector (ถ้ามี) + TF‑IDF + facts จาก KG
   - แมปผลเป็นชื่อเอกสารที่น่าจะใช่ เช่น “คำฟ้องคดีแรงงาน รง1 / ศาลแรงงานกลาง” → ตอบกลับให้หน้าเว็บ

3. ค้นหา/ตอบคำถาม (Search/Answer)
   - `/search`: คืนเอกสารใกล้เคียง + facts จาก KG
   - `/answer`: สังเคราะห์คำตอบโดยอ้างอิง doc hits + facts (สำหรับ UI อธิบาย/ประกอบ)

## ส่วนประกอบซอฟต์แวร์ (Components)

- Next.js App: UI, debounce, validation, UX
- Next API Route: `/app/api/court-documents/route.ts` (Proxy ไป Backend ตาม `BACKEND_URL`)
- FastAPI: `/src/api/routes.py`
  - `/ingest`, `/search`, `/answer`, `/court-documents/search`, `/Health`
- Services:
  - `extraction.py`: rule‑based แยกเอนทิตี/ความสัมพันธ์
  - `neo4j_service.py`: คุยกับ Neo4j (constraints/upsert/query)
  - `search.py`: Hybrid Search (vector+TF‑IDF) และรวม facts จากกราฟ
- Neo4j: โหนด Person/CourtCase/Date/MoneyAmount/Section/... + DocChunk

## โครงสร้างข้อมูลหลัก (Neo4j Schema ย่อ)

```text
(Person)-[:HAS_ROLE]->(LegalRole)
(Person)-[:PARTY]->(CourtCase)
(CourtCase)-[:HAS_AMOUNT]->(MoneyAmount)
(CourtCase)-[:OCCURRED_ON]->(Date)
(Section)-[:HAS_DESC]->(Section_desc)
(Section)-[:SECTION]->(Group)
(CourtCase) --(metadata/docs)--> (DocChunk {caseId, chunkId, text, page, section})
```

## Hybrid Search (แนวคิด)

- TF‑IDF: เน้นคีย์เวิร์ดตรง เหมาะกับศัพท์เฉพาะ
- Vector (Embeddings): เข้าใจความหมาย/คำพ้อง แม้พิมพ์ไม่เป๊ะ (ต้องมี `OPENAI_API_KEY`)
- การรวมคะแนน: 0.7 (vector) + 0.3 (TF‑IDF); ถ้าไม่มีเวกเตอร์ ใช้ TF‑IDF อย่างเดียว
- ใช้ facts จาก KG เพื่อประกอบ/ตรวจสอบผลลัพธ์

## Non-Functional Requirements (NFRs)

- Performance: Debounce ฝั่ง UI; Backend ทำ hybrid ชุดเล็ก เร็วพอสำหรับ interactive suggestion
- Scalability:
  - แนวทางระยะสkal: เพิ่ม vector index จริง (Neo4j vector index/Qdrant), cache doc embeddings, horizontal scale FastAPI
  - Neo4j: ปรับขนาด instance/cluster ตามโหลด
- Availability: แยก FE/BE/DB; readiness checks (`/Health`), graceful restarts
- Security:
  - ซ่อน BACKEND_URL หลัง Next API Route
  - เก็บ secrets (`OPENAI_API_KEY`, Neo4j user/pass) ใน env/secret manager
  - CORS เปิดไว้กว้างตอน dev ปรับให้จำกัด origin ใน prod
- Observability:
  - เพิ่ม access log/metrics/traces ใน FastAPI
  - ใช้ Neo4j Browser/queries ตรวจข้อมูลจริง

## Environment & Config

- Frontend
  - `.env`: `BACKEND_URL=http://localhost:8000`
- Backend (`src/config.py` อ่าน env)
  - `NEO4J_URI` (default `bolt://localhost:7687`)
  - `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`
  - (optional) `OPENAI_API_KEY` สำหรับ embeddings

## Deployment (แนะนำ)

- Dev: run Neo4j local, `python backend/NEO4j/run_api.py`, Next.js dev server
- Prod (ตัวอย่าง):
  - FE: Next.js on Vercel/Container
  - BE: FastAPI (Uvicorn/Gunicorn) on container/K8s, behind reverse proxy
  - DB: Neo4j Aura หรือ self-managed cluster
  - ตั้ง health checks, autoscaling policies, log/metrics pipelines

## ความเสี่ยงและการบรรเทา (Risks & Mitigations)

- ไม่มี embeddings → คุณภาพเดาลดลง: ใช้ TF‑IDF ต่อได้, วางแผนทำ vector index ภายหลัง
- ข้อมูลไม่สม่ำเสมอ → ปรับกฎ extraction, ตรวจสอบคุณภาพ ingest
- โหลดค้นหาสูง → เปิด cache/ANN index, scale out BE
- ความปลอดภัย → จำกัด CORS, ใส่ Auth/Rate Limit ตามบริบทงานจริง

## Quick Check (สำหรับ SA)

- Topology: Web → Proxy → FastAPI → Neo4j (+ OpenAI optional)
- เส้นทาง Step 1: UI (debounce) → /court-documents/search → Hybrid → แนะนำเอกสาร
- แยกชั้นชัดเจน: UI/Proxy/Service/Data; ปรับสเกลง่าย เพิ่มความสามารถได้เป็นโมดูล

---

## อธิบายแบบง่ายสำหรับ SA มือใหม่ (อ่านสบาย เข้าใจเร็ว)

ลองจินตนาการว่าเราทำ “ร้านหนังสือกฎหมายแรงงานออนไลน์” ที่ฉลาดขึ้นด้วยกราฟความรู้

- ผู้ใช้พิมพ์ว่า “เลิกจ้างไม่เป็นธรรม” เหมือนถามพนักงานร้าน
- ระบบจะทั้ง “เดาความหมาย” (Vector) และ “ดูคำตรงๆ” (TF‑IDF) พร้อมกับ “เช็คสมุดบันทึกความสัมพันธ์” (Knowledge Graph/Neo4j)
- จากนั้นพนักงาน (Backend) จะเสนอหนังสือ/แบบคำฟ้องที่น่าจะใช่ (เช่น “คำฟ้องคดีแรงงาน รง1 / ศาลแรงงานกลาง”) ให้ลูกค้าเลือก

### ทำไมต้องมี Proxy ของ Next.js?

- เหมือนแคชเชียร์กลาง: หน้าเว็บ (FE) ไม่คุยกับ Backend ตรงๆ แต่ผ่านทางเดินกลาง (Next API Route) เพื่อซ่อน URL Backend, เพิ่มความปลอดภัย และจัดรูปแบบเรียกใช้ง่ายในทีม FE

### อธิบายทุกชิ้นแบบภาษาคน

- Frontend (Next.js): หน้าร้าน/เคาน์เตอร์รับคำถาม มีช่องให้พิมพ์, เด้งคำแนะนำเร็ว (debounce)
- Next API Route (Proxy): ทางเดินกลางจากร้านไปคลังสินค้า (Backend), ช่วยซ่อน BACKEND_URL และควบคุมทราฟฟิก
- FastAPI (Backend): คลังที่มีพนักงานเก่งๆ รู้ว่า “คำที่พิมพ์” ใกล้เคียงอะไรบ้าง (TF‑IDF) และ “ความหมาย” ใกล้เคียงอะไรบ้าง (Vector), แล้วไปเปิดสมุดความรู้ (Neo4j) ประกอบคำตอบ
- Neo4j (Knowledge Graph): สมุดบันทึกแบบแผนผัง ที่บอกว่าใครเป็นใคร เหตุการณ์เมื่อไหร่ จำนวนเงินเท่าไหร่ มาตราอะไรเกี่ยวข้อง ช่วยให้คำตอบมีโครงสร้างตรวจสอบได้
- OpenAI (Embeddings, เลือกใช้): เครื่องมือช่วย “เข้าใจความหมาย” ของประโยค เพื่อเดาให้แม่นเวลาผู้ใช้พิมพ์ไม่ตรงคำศัพท์เป๊ะๆ

### เวลา “ผู้ใช้พิมพ์” เกิดอะไรขึ้นทีละขั้น (ย้ำอีกครั้งแบบง่ายๆ)

1. ผู้ใช้พิมพ์คำในฟอร์ม → FE หน่วง 350ms กันยิงถี่เกินไป
2. FE เรียก `/api/court-documents?q=...` (ผ่านทางเดินกลาง)
3. Proxy ส่งต่อไป Backend `/court-documents/search`
4. Backend ทำ Hybrid Search:
   - คิดคะแนน “ความหมาย” (Vector, ถ้ามีคีย์ OpenAI)
   - คิดคะแนน “คำตรงๆ” (TF‑IDF)
   - รวมคะแนน = 0.7 Vector + 0.3 TF‑IDF (ถ้าไม่มี Vector ใช้ TF‑IDF อย่างเดียว)
   - เปิด Neo4j ดู facts ที่เกี่ยวข้อง (บุคคล/บทบาท/จำนวนเงิน/วันที่/มาตรา)
5. แปลงผลออกมาเป็น “คำแนะนำเอกสารศาล” ที่เข้าใจง่ายสำหรับผู้ใช้
6. FE แสดงคำแนะนำใต้ช่องกรอก และมีตัวตรวจว่ากรอกครบหรือยัง (ประเภทเอกสาร + ศาล)

### ตัวอย่างเรียกใช้งานจริง (เพื่อ SA จะได้ลองตาม)

- เช็คสุขภาพระบบ Backend:

```bash
curl 'http://localhost:8000/Health'
```

- ขอคำแนะนำเอกสารศาลจากข้อความผู้ใช้:

```bash
curl 'http://localhost:8000/court-documents/search?q=เลิกจ้างไม่เป็นธรรม'
```

- ค้นหาเอกสารและข้อมูลกราฟแบบกว้างๆ:

```bash
curl 'http://localhost:8000/search?q=เลิกจ้างไม่เป็นธรรม'
```

### คำศัพท์ (Glossary) ที่ควรรู้

- TF‑IDF: การค้นแบบ “คำตรงๆ” (ดีเมื่อศัพท์เหมือนกัน), เร็วและเบา
- Vector/Embeddings: การค้นแบบ “ความหมาย” (ดีเมื่อพิมพ์ไม่ตรง/คำพ้อง), ต้องมีโมเดลช่วย
- Knowledge Graph (KG): โครงสร้างข้อมูลแบบโหนด/ความสัมพันธ์ ช่วยตอบคำถามที่ต้อง “อ้างอิงได้” เช่น ใคร เป็นอะไร กับใคร เมื่อไหร่
- DocChunk: ชิ้นข้อความของเอกสารที่แบ่งไว้เพื่อค้นหาได้ละเอียดขึ้น
- Hybrid Search: ผสม Vector + TF‑IDF + KG facts เพื่อให้ทั้ง “แม่นความหมาย” และ “ตรวจสอบได้”
- Debounce: เทคนิคหน่วงเวลาเล็กน้อยก่อนยิงคำค้น เพื่อประหยัดทรัพยากรและลื่นไหล

### ทำอย่างไรให้รองรับโหลด/สเกลมากขึ้น (พูดแบบง่าย)

- เพิ่มดัชนีเวกเตอร์จริง (Neo4j vector index หรือ Qdrant) → ค้นแบบความหมายได้เร็วขึ้นแม้ข้อมูลเยอะ
- แคช embeddings ของเอกสารไว้ล่วงหน้า → ลดเวลาคิดซ้ำ
- ขยาย FastAPI แบบแนวนอน (หลาย replica หลัง load balancer) → รองรับผู้ใช้มากขึ้น
- Neo4j ใช้บริการ managed (เช่น Aura) หรือทำ cluster เอง → เชื่อถือได้มากขึ้น

### ความปลอดภัย/การตั้งค่า ที่มักลืม (ย้ำสำหรับมือใหม่)

- เก็บ `OPENAI_API_KEY` และรหัส Neo4j ใน secret/ENV อย่าใส่ในโค้ด
- เปิด CORS อย่างจำกัดใน production (ตอน dev อาจกว้าง)
- Proxy ช่วยซ่อน URL Backend จาก FE ตรงๆ

### ถ้าเกิดปัญหา จะเช็คยังไง (Troubleshooting)

- เปิดดู `/Health` ก่อน ว่าตัว Backend ตอบไหม
- ถ้าแนะนำเอกสารไม่ขึ้น: เช็คว่า FE ยิง `/api/court-documents` แล้วหรือยัง และ Backend ตอบ status 200 ไหม
- ถ้าคำแนะนำไม่แม่น: ตรวจว่าใส่ `OPENAI_API_KEY` แล้วหรือยัง (ถ้าไม่ใส่จะใช้ TF‑IDF อย่างเดียว)
- ถ้า KG ว่าง: ลอง `/ingest` ใส่ตัวอย่างข้อความ เพื่อให้มีโหนด/ความสัมพันธ์ใน Neo4j ก่อน

### ทางลัดจำง่าย (TL;DR)

- Web (FE) → Proxy → Backend → Neo4j (+ OpenAI แบบเลือกใช้)
- เดาความหมาย (Vector) + คำตรงๆ (TF‑IDF) + อ้างอิงจากกราฟ (KG) = คำแนะนำที่ “ฉลาดและตรวจสอบได้”
- ไม่มีคีย์ OpenAI ก็ยังใช้งานได้ (แค่ความฉลาดลดลง แต่ระบบยังทำงาน)
