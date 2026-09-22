"""Tests for document discrepancy detection (rules-based, no AI key required)."""

import asyncio
from datetime import date

import pytest

from bim_coordination_ai.document_diff import DocumentDiffService
from bim_coordination_ai.models import (
    Discipline,
    DocumentComparisonRequest,
    DocumentRevision,
    DocumentType,
    Priority,
)

svc = DocumentDiffService()


def _doc(**kwargs) -> DocumentRevision:
    defaults = dict(
        doc_id="D-001",
        filename="L3-STR-100.pdf",
        doc_type=DocumentType.PDF,
        discipline=Discipline.STRUCTURE,
        revision="P02",
        issue_date=date(2026, 6, 1),
        issued_by="Struct Engineering Ltd",
        content_summary="",
    )
    defaults.update(kwargs)
    return DocumentRevision(**defaults)


def compare(received: DocumentRevision, bim_output: DocumentRevision):
    return asyncio.run(svc.compare(DocumentComparisonRequest(received=received, bim_output=bim_output)))


# ── No issues ─────────────────────────────────────────────────────────────────

def test_identical_metadata_no_discrepancies():
    received = _doc(doc_id="R-001")
    bim = _doc(doc_id="B-001")
    result = compare(received, bim)
    assert result.discrepancy_count == 0
    assert not result.requires_human_review


# ── Revision checks ───────────────────────────────────────────────────────────

def test_bim_behind_received_is_high():
    received = _doc(doc_id="R-001", revision="P04")
    bim = _doc(doc_id="B-001", revision="P02")
    result = compare(received, bim)
    high_discs = [d for d in result.discrepancies if d.severity == Priority.HIGH]
    assert high_discs, "Expected HIGH discrepancy for outdated BIM revision"
    assert result.requires_human_review


def test_bim_ahead_of_received_is_medium():
    received = _doc(doc_id="R-001", revision="P01")
    bim = _doc(doc_id="B-001", revision="P03")
    result = compare(received, bim)
    medium_discs = [d for d in result.discrepancies if d.severity == Priority.MEDIUM]
    assert medium_discs


def test_matching_revisions_no_revision_discrepancy():
    received = _doc(doc_id="R-001", revision="C03")
    bim = _doc(doc_id="B-001", revision="C03")
    result = compare(received, bim)
    rev_discs = [d for d in result.discrepancies if "revision" in d.description.lower()]
    assert not rev_discs


# ── Discipline check ──────────────────────────────────────────────────────────

def test_discipline_mismatch_is_high():
    received = _doc(doc_id="R-001", discipline=Discipline.STRUCTURE)
    bim = _doc(doc_id="B-001", discipline=Discipline.MEP)
    result = compare(received, bim)
    assert any(d.severity == Priority.HIGH for d in result.discrepancies)
    assert result.requires_human_review


# ── Date check ────────────────────────────────────────────────────────────────

def test_received_newer_than_bim_is_medium():
    received = _doc(doc_id="R-001", issue_date=date(2026, 7, 1))
    bim = _doc(doc_id="B-001", issue_date=date(2026, 5, 1))
    result = compare(received, bim)
    date_discs = [d for d in result.discrepancies if "dated" in d.description.lower()]
    assert date_discs
    assert all(d.severity == Priority.MEDIUM for d in date_discs)


# ── Text content diff ─────────────────────────────────────────────────────────

def test_element_count_divergence_flagged():
    received = _doc(
        doc_id="R-001",
        content_summary="column column column column column column beam beam slab",
    )
    bim = _doc(
        doc_id="B-001",
        content_summary="beam beam slab",  # 6 fewer 'column' mentions
    )
    result = compare(received, bim)
    text_discs = [d for d in result.discrepancies if "column" in d.description]
    assert text_discs


def test_consistent_content_no_text_discrepancies():
    content = "beam column slab wall door window"
    received = _doc(doc_id="R-001", content_summary=content)
    bim = _doc(doc_id="B-001", content_summary=content)
    result = compare(received, bim)
    text_discs = [
        d for d in result.discrepancies
        if any(kw in d.description for kw in ("column", "beam", "slab", "wall"))
    ]
    assert not text_discs


# ── Summary string ────────────────────────────────────────────────────────────

def test_summary_mentions_human_review_when_needed():
    received = _doc(doc_id="R-001", revision="P05")
    bim = _doc(doc_id="B-001", revision="P01")
    result = compare(received, bim)
    assert "REQUIRED" in result.summary


def test_summary_safe_when_no_discrepancies():
    received = _doc(doc_id="R-001")
    bim = _doc(doc_id="B-001")
    result = compare(received, bim)
    assert "safe to proceed" in result.summary.lower()
