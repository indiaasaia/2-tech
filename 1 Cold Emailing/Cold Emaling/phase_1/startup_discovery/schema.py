"""Pydantic models describing the structured JSON Gemini must return.

These double as the `response_format.schema` sent to the API (schema
enforcement server-side) and as the documentation of the machine contract
between Gemini and the application.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Company(BaseModel):
    rank: Optional[int] = Field(default=None, description="Rank of the company within this batch (1-based).")
    company_name: str = Field(description="Official company name.")
    website: str = Field(description="Official website URL, e.g. https://example.com")
    location: str = Field(description="City/country, e.g. 'Berlin, Germany'.")
    company_size: str = Field(description="Estimated size, e.g. '11-50 employees'.")
    startup_stage: str = Field(description="Stage, e.g. 'Seed', 'Series A', 'Scale-up'.")
    technical_focus: str = Field(description="Technical areas, e.g. 'AI/ML, backend engineering'.")
    relevant_roles: str = Field(description="Roles relevant to the target candidate.")
    english_hiring_evidence: str = Field(
        description="Concrete, observable evidence that English is used or sufficient. Never 'Not verified.'."
    )
    student_intern_evidence: str = Field(
        description="Concrete evidence of student/intern/junior hiring, current or historical. Never 'Not verified.'."
    )
    current_hiring_evidence: str = Field(
        description="Evidence of current/recent hiring activity. 'Not verified.' is allowed here."
    )
    cold_outreach_potential: str = Field(description="Why direct outreach could realistically work.")
    hiring_probability_score: int = Field(description="Structured research score from 0 to 100.")
    priority: str = Field(description="Classification: Very High / High / Medium priority.")
    why_target: str = Field(description="Concise explanation why this company is a target.")
    sources: list[str] = Field(description="Source URLs supporting the evidence claims.")


class DiscoveryResponse(BaseModel):
    companies: list[Company] = Field(
        default_factory=list,
        description="Newly discovered companies. Empty when no new qualifying companies exist.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Optional free text: research limitations, why fewer than requested were returned, etc.",
    )
