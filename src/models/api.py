"""Pydantic models for API requests and responses"""

from typing import Optional, List
from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    """Request model for document ingestion"""
    texts: List[str] = Field(
        ..., 
        description="ข้อความคดีเป็นลิสต์ของชิ้นข้อความ",
        example=[
            "เมื่อวันที่ 1 พฤศจิกายน 2557 จำเลยได้จ้างโจทก์เข้าทำงานเป็นลูกจ้างในตำแหน่ง แม่บ้านได้รับค่าจ้างเป็นรายเดือนอัตราค่าจ้างสุดท้ายเดือนละ 10,000 บาทกำหนดจ่ายค่าจ้างทุกวันสิ้นเดือน"
        ],
    )
    case_id: Optional[str] = Field(
        None,
        description="ถ้าไม่ส่งหรือเป็น 'string' ระบบจะตรวจจับ/สร้างอัตโนมัติ",
        example=None,
    )


class AskRequest(BaseModel):
    """Request model for question answering"""
    question: str
    case_id: Optional[str] = None
    k: int = 5


class IngestResponse(BaseModel):
    """Response model for document ingestion"""
    case_id: str
    chunks: int


class FactResponse(BaseModel):
    """Response model for facts retrieval"""
    case_id: str
    facts: List[dict]


class ChunkResponse(BaseModel):
    """Response model for document chunks"""
    case_id: str
    chunks: List[dict]


class SearchResponse(BaseModel):
    """Response model for search queries"""
    query: str
    case_id: Optional[str]
    top_docs: List[dict]
    facts: List[dict]


class AnswerResponse(BaseModel):
    """Response model for question answering"""
    query: str
    case_id: Optional[str]
    answer: str
    doc_hits: List[dict]
    facts: List[dict]
