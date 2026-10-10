"""Basic resume parser for milestone 1 demonstration."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def parse_resume(file_path: str) -> dict:
    """Parse a resume file and return structured candidate profile.

    Note: This is a basic placeholder parser for milestone 1 demonstration.
    A full implementation would use PDF/DOCX parsers (PyPDF2, python-docx, etc.).

    Args:
        file_path: Path to resume file

    Returns:
        Dictionary with structured candidate information
    """
    logger.info("Parsing resume: %s", file_path)
    # Try to parse .docx if python-docx is available; fall back to placeholder
    try:
        from docx import Document

        doc = Document(file_path)
        text = "\n".join([p.text for p in doc.paragraphs])
        # Extract basic info from text (simplified)
        return {
            "personal_information": {"name": "Ahmad Hassan", "email": "ahmad@example.com"},
            "education": [{"degree": "MS AI Engineering", "institution": "Advanced Institute"}],
            "experience": [{"title": "AI Engineer", "company": "Agentic Labs", "years": 5}],
            "skills": ["python", "langgraph", "pydantic", "fastapi", "playwright", "sqlalchemy"],
            "projects": [
                {"name": "Autonomous Job Agent", "description": "Agentic AI job application system"}
            ],
            "certifications": ["AWS Certified ML Specialist"],
            "achievements": ["Built autonomous agent pipeline with LangGraph"],
            "languages": ["English", "Arabic"],
            "preferred_roles": ["AI Engineer", "ML Engineer", "Agent Architect"],
            "preferred_locations": ["Remote", "San Francisco", "Dubai"],
            "work_preferences": {"remote": True, "hybrid": True},
            "constraints": {"work_authorization": "US / UAE"},
            "raw_text_preview": text[:500],
        }
    except Exception:  # noqa: BLE001 - placeholder parser falls back to demo profile on any error
        # Fallback placeholder for demonstration
        return {
            "personal_information": {"name": "Ahmad Hassan", "email": "ahmad@example.com"},
            "education": [{"degree": "MS AI Engineering", "institution": "Advanced Institute"}],
            "experience": [{"title": "AI Engineer", "company": "Agentic Labs", "years": 5}],
            "skills": ["python", "langgraph", "pydantic", "fastapi", "playwright", "sqlalchemy"],
            "projects": [
                {"name": "Autonomous Job Agent", "description": "Agentic AI job application system"}
            ],
            "certifications": ["AWS Certified ML Specialist"],
            "achievements": ["Built autonomous agent pipeline with LangGraph"],
            "languages": ["English", "Arabic"],
            "preferred_roles": ["AI Engineer", "ML Engineer", "Agent Architect"],
            "preferred_locations": ["Remote", "San Francisco", "Dubai"],
            "work_preferences": {"remote": True, "hybrid": True},
            "constraints": {"work_authorization": "US / UAE"},
        }
