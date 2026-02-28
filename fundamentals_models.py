"""
SQLAlchemy ORM models for the Fundamentals Reports feature.

Tables
------
companies       – one row per ticker symbol
filings         – one row per SEC accession number
filing_text     – extracted / cleaned text for a filing (1-to-1 with filings)
report_outputs  – cached LLM-generated JSON + rendered HTML
"""
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date,
    ForeignKey, JSON, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from fundamentals_db import Base


class Company(Base):
    __tablename__ = "fn_companies"

    id         = Column(Integer, primary_key=True)
    ticker     = Column(String(20),  unique=True, nullable=False, index=True)
    cik        = Column(String(20),  nullable=True)
    name       = Column(String(255), nullable=True)
    exchange   = Column(String(50),  nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    filings = relationship("Filing", back_populates="company", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Company {self.ticker}>"


class Filing(Base):
    __tablename__ = "fn_filings"

    id              = Column(Integer, primary_key=True)
    company_id      = Column(Integer, ForeignKey("fn_companies.id"), nullable=False)
    filing_id       = Column(String(100), unique=True, nullable=False, index=True)  # SEC accession number
    filing_type     = Column(String(20),  nullable=False)   # 10-Q / 10-K / 8-K
    period_end      = Column(Date,        nullable=True)
    filed_at        = Column(DateTime,    nullable=True)
    source_url      = Column(String(1000), nullable=True)
    source_provider = Column(String(50),  default="sec")
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company        = relationship("Company",     back_populates="filings")
    filing_text    = relationship("FilingText",  back_populates="filing",
                                  uselist=False, cascade="all, delete-orphan")
    report_outputs = relationship("ReportOutput", back_populates="filing",
                                  cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Filing {self.filing_id} ({self.filing_type})>"


class FilingText(Base):
    __tablename__ = "fn_filing_text"

    id           = Column(Integer, primary_key=True)
    filing_id    = Column(Integer, ForeignKey("fn_filings.id"), nullable=False, unique=True)
    raw_html     = Column(Text,  nullable=True)           # first ~100 k chars of raw HTML
    clean_text   = Column(Text,  nullable=False, default="")
    chunks_json  = Column(JSON,  nullable=True)           # list[str] of text chunks
    extracted_at = Column(DateTime, default=datetime.utcnow)

    filing = relationship("Filing", back_populates="filing_text")

    def __repr__(self):
        return f"<FilingText filing_id={self.filing_id}>"


class ReportOutput(Base):
    __tablename__ = "fn_report_outputs"

    id             = Column(Integer, primary_key=True)
    filing_id      = Column(Integer, ForeignKey("fn_filings.id"), nullable=False)
    schema_version = Column(String(50), default="ReportData/v1")
    report_json    = Column(JSON,  nullable=True)
    rendered_html  = Column(Text,  nullable=True)
    llm_model      = Column(String(100), nullable=True)
    llm_meta       = Column(JSON,  nullable=True)
    # error_state: None | 'llm_error' | 'schema_error'
    error_state    = Column(String(50), nullable=True)
    error_message  = Column(Text, nullable=True)
    # ── Earnings Expectations & Market Reaction Engine ───────────────────────
    consensus_json        = Column(JSON, nullable=True)  # analyst expectations
    surprise_json         = Column(JSON, nullable=True)  # beat/miss percentages
    market_analysis_json  = Column(JSON, nullable=True)  # LLM reaction analysis
    narrative_change_json = Column(JSON, nullable=True)  # LLM narrative comparison
    # ────────────────────────────────────────────────────────────────────────
    created_at     = Column(DateTime, default=datetime.utcnow)

    filing = relationship("Filing", back_populates="report_outputs")

    def __repr__(self):
        return f"<ReportOutput filing_id={self.filing_id} schema={self.schema_version}>"
