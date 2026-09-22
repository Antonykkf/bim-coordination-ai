"""
Document discrepancy detector: DWG/PDF (received) vs BIM output PDF.

Rules-based baseline runs always.  When AI_API_KEY is set the service posts
both document summaries to the LLM and merges any additional findings.

All results are advisory.  HIGH/CRITICAL discrepancies are flagged for human
BIM coordinator review before any TIDP update is submitted.
"""

import json
import os
import re

import httpx

from .models import (
    Discrepancy,
    DocumentComparisonRequest,
    DocumentComparisonResult,
    DocumentRevision,
    Priority,
)

# Keywords that map to structural / MEP elements — used for text-level diffing
_ELEMENT_KEYWORDS: tuple[str, ...] = (
    "column",
    "beam",
    "slab",
    "wall",
    "opening",
    "door",
    "window",
    "duct",
    "pipe",
    "sprinkler",
    "stair",
    "ramp",
    "grid",
    "level",
    "setout",
    "offset",
)

_REVISION_DIGITS = re.compile(r"(\d+)")


def _revision_number(rev: str) -> int | None:
    """Extract leading integer from a revision string, e.g. 'P02' → 2."""
    m = _REVISION_DIGITS.search(rev)
    return int(m.group(1)) if m else None


class DocumentDiffService:
    """Compare a received DWG/PDF against the BIM team's latest output."""

    # ── Public entry point ────────────────────────────────────────────────────

    async def compare(self, req: DocumentComparisonRequest) -> DocumentComparisonResult:
        received = req.received
        bim = req.bim_output

        discrepancies: list[Discrepancy] = []

        # 1. Discipline match
        discrepancies.extend(self._check_discipline(received, bim))

        # 2. Revision currency
        discrepancies.extend(self._check_revision(received, bim))

        # 3. Date plausibility
        discrepancies.extend(self._check_dates(received, bim))

        # 4. Text-level element keyword diff (when content is provided)
        if received.content_summary and bim.content_summary:
            discrepancies.extend(self._diff_text(received, bim))

        # 5. Optional AI enrichment
        if os.getenv("AI_API_KEY") and (received.content_summary or bim.content_summary):
            ai_findings = await self._ai_enrich(received, bim, discrepancies)
            discrepancies.extend(ai_findings)

        requires_review = any(
            d.severity in (Priority.CRITICAL, Priority.HIGH) for d in discrepancies
        )
        confidence = 0.85 if discrepancies else 0.90

        return DocumentComparisonResult(
            doc_id_received=received.doc_id,
            doc_id_bim=bim.doc_id,
            discrepancies=discrepancies,
            discrepancy_count=len(discrepancies),
            summary=self._build_summary(discrepancies, received, bim),
            requires_human_review=requires_review,
            confidence=confidence,
        )

    # ── Rules checks ──────────────────────────────────────────────────────────

    @staticmethod
    def _check_discipline(
        received: DocumentRevision, bim: DocumentRevision
    ) -> list[Discrepancy]:
        if received.discipline == bim.discipline:
            return []
        return [
            Discrepancy(
                description=(
                    f"Discipline mismatch: received document is '{received.discipline}' "
                    f"but BIM output is '{bim.discipline}'. "
                    "Confirm correct file was issued and BIM package aligns."
                ),
                severity=Priority.HIGH,
                recommendation="Cross-check transmittal schedule and reissue if needed.",
            )
        ]

    @staticmethod
    def _check_revision(
        received: DocumentRevision, bim: DocumentRevision
    ) -> list[Discrepancy]:
        r_num = _revision_number(received.revision)
        b_num = _revision_number(bim.revision)

        if r_num is None or b_num is None:
            # Cannot parse — do a string comparison
            if received.revision.upper() != bim.revision.upper():
                return [
                    Discrepancy(
                        description=(
                            f"Revision mismatch: received '{received.revision}' vs "
                            f"BIM output '{bim.revision}'. Verify currency."
                        ),
                        severity=Priority.MEDIUM,
                        recommendation="Confirm which revision is current and align BIM model.",
                    )
                ]
            return []

        if b_num < r_num:
            return [
                Discrepancy(
                    description=(
                        f"BIM output is at revision {bim.revision} but the received document "
                        f"is at {received.revision}. BIM model is behind — update required."
                    ),
                    severity=Priority.HIGH,
                    recommendation=(
                        "Incorporate received revision into BIM model and reissue "
                        "before submitting TIDP response."
                    ),
                )
            ]

        if b_num > r_num:
            return [
                Discrepancy(
                    description=(
                        f"BIM output revision {bim.revision} is ahead of received "
                        f"{received.revision}. Confirm the received document is the latest issue."
                    ),
                    severity=Priority.MEDIUM,
                    recommendation="Request latest revision from originator to confirm alignment.",
                )
            ]

        return []

    @staticmethod
    def _check_dates(
        received: DocumentRevision, bim: DocumentRevision
    ) -> list[Discrepancy]:
        discs: list[Discrepancy] = []
        if received.issue_date > bim.issue_date:
            discs.append(
                Discrepancy(
                    description=(
                        f"Received document is dated {received.issue_date}, which is "
                        f"newer than BIM output dated {bim.issue_date}. "
                        "BIM model may not reflect the latest information."
                    ),
                    severity=Priority.MEDIUM,
                    recommendation=(
                        "Review received document for changes since BIM output date "
                        "and update model accordingly."
                    ),
                )
            )
        return discs

    @staticmethod
    def _diff_text(
        received: DocumentRevision, bim: DocumentRevision
    ) -> list[Discrepancy]:
        """Flag elements mentioned significantly more/less often between the two docs."""
        discs: list[Discrepancy] = []
        r_lower = received.content_summary.lower()
        b_lower = bim.content_summary.lower()

        for kw in _ELEMENT_KEYWORDS:
            r_count = r_lower.count(kw)
            b_count = b_lower.count(kw)
            delta = abs(r_count - b_count)
            if delta >= 3:
                direction = (
                    f"received mentions {r_count} vs BIM output {b_count}"
                    if r_count != b_count
                    else "equal"
                )
                discs.append(
                    Discrepancy(
                        description=(
                            f"'{kw}' count diverges between documents ({direction}). "
                            "May indicate added/removed elements."
                        ),
                        severity=Priority.MEDIUM,
                        recommendation=f"Check '{kw}' elements for additions, deletions, or relocations.",
                    )
                )
        return discs

    # ── AI enrichment ─────────────────────────────────────────────────────────

    async def _ai_enrich(
        self,
        received: DocumentRevision,
        bim: DocumentRevision,
        existing: list[Discrepancy],
    ) -> list[Discrepancy]:
        """Ask the configured LLM for additional discrepancies not caught by rules."""
        existing_desc = "; ".join(d.description for d in existing) or "none"
        prompt = (
            "You are a senior BIM coordinator reviewing two documents for discrepancies. "
            "Identify any additional discrepancies NOT already listed. "
            "Respond with a JSON array of objects: "
            '[{"description": "...", "severity": "critical|high|medium|low", '
            '"recommendation": "..."}]. '
            "Return an empty array if no additional issues are found. "
            "Flag life-safety items as critical.\n\n"
            f"Received document ({received.filename} Rev {received.revision}):\n"
            f"{received.content_summary}\n\n"
            f"BIM output ({bim.filename} Rev {bim.revision}):\n"
            f"{bim.content_summary}\n\n"
            f"Already identified issues: {existing_desc}"
        )

        api_key = os.environ.get("AI_API_KEY", "")
        base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        model = os.getenv("AI_MODEL", "gpt-4.1-mini")

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0,
                    },
                )
                response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
            items = json.loads(raw)
            if not isinstance(items, list):
                return []
            return [
                Discrepancy(
                    description=str(item.get("description", "")),
                    severity=Priority(item.get("severity", "medium")),
                    recommendation=str(item.get("recommendation", "")),
                )
                for item in items
                if item.get("description")
            ]
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return []

    # ── Summary builder ───────────────────────────────────────────────────────

    @staticmethod
    def _build_summary(
        discrepancies: list[Discrepancy],
        received: DocumentRevision,
        bim: DocumentRevision,
    ) -> str:
        if not discrepancies:
            return (
                f"No discrepancies found between received '{received.filename}' "
                f"(Rev {received.revision}, {received.issue_date}) and BIM output "
                f"'{bim.filename}' (Rev {bim.revision}, {bim.issue_date}). "
                "Documents appear aligned — safe to proceed with TIDP update."
            )
        counts = {p: 0 for p in Priority}
        for d in discrepancies:
            counts[d.severity] += 1

        human_review = any(
            d.severity in (Priority.CRITICAL, Priority.HIGH) for d in discrepancies
        )
        return (
            f"Comparison of '{received.filename}' vs '{bim.filename}': "
            f"{len(discrepancies)} discrepancy/ies — "
            f"critical={counts[Priority.CRITICAL]}, "
            f"high={counts[Priority.HIGH]}, "
            f"medium={counts[Priority.MEDIUM]}, "
            f"low={counts[Priority.LOW]}. "
            f"Human BIM coordinator review {'REQUIRED' if human_review else 'not required'} "
            "before TIDP update submission."
        )
