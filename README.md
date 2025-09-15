# Neo — Legal Knowledge Graph (TH)

เดโมสร้าง Knowledge Graph จากข้อความคดีภาษาไทยแบบ rule-based และค้นหาแบบ Hybrid (TF‑IDF + กราฟ) เก็บใน Neo4j ใช้งานได้ทั้ง CLI และ REST API (Swagger `/docs`).

## ติดตั้งแบบเร็ว


2. สร้าง .env ในโฟลเดอร์โปรเจกต์:



3. ติดตั้งไลบรารี (แนะนำ venv):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install fastapi uvicorn neo4j python-dotenv pydantic
```

## ใช้งาน CLI

```bash
python main.py
```

ผลลัพธ์จะแสดง Case ID, ขั้นตอน Extract/Upsert และคำตอบสรุป ข้อมูลถูกบันทึกใน Neo4j แล้ว

ตรวจใน Neo4j Browser (`http://localhost:7474`):

```cypher
MATCH (c:CourtCase) RETURN c.caseId, c.name LIMIT 5;
MATCH (p:Person)-[:PARTY]->(c:CourtCase) RETURN p.name, c.caseId LIMIT 10;
MATCH (t:LegalTerm {name:'ค่าจ้าง'})-[:HAS_AMOUNT]->(m:MoneyAmount) RETURN m.name LIMIT 5;
MATCH (d:DocChunk) RETURN d.caseId, d.page, left(d.text, 60) AS preview LIMIT 5;
```

## ใช้งาน API (Swagger)

รันเซิร์ฟเวอร์ FastAPI:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

เปิด Swagger: `http://localhost:8000/docs`

ลำดับแนะนำ:

1. `POST /ingest` ใส่ข้อความคดีเพื่อสร้างกราฟและเก็บชิ้นเอกสาร
2. ถามผ่าน `GET /answer` หรือ `POST /ask`

ตัวอย่างคำขอ:

- Ingest

```bash
curl -X POST http://localhost:8000/ingest \
  -H 'Content-Type: application/json' \
  -d '{
    "texts": [
      "เมื่อวันที่ 1 พฤศจิกายน 2557 จำเลยได้จ้างโจทก์เข้าทำงาน...",
      "ได้รับค่าจ้างเป็นรายเดือนอัตราค่าจ้างสุดท้ายเดือนละ 10,000 บาท..."
    ]
  }'
```

- ถาม (POST /ask)

```bash
curl -X POST http://localhost:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "โจทก์เรียกร้องค่าจ้างเท่าไร และมีเหตุการณ์เมื่อวันไหน",
    "k": 5
  }'
```

- ถาม (GET /answer)

```bash
curl "http://localhost:8000/answer?q=โจทก์เรียกร้องค่าจ้างเท่าไร&k=5"
```

## หมายเหตุ

- ถ้าเจอ ServiceUnavailable routing ให้ตั้ง `NEO4J_URI=bolt://localhost:7687`
- คำเตือน UnknownPropertyKey `section` ไม่กระทบการทำงาน
