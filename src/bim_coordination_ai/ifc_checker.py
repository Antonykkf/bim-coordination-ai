"""
IFC model quality checker.

Validates three categories for every IfcProduct in the file:

1. Naming convention  — element Name must match a configurable regex
                        (default: ISO 19650-style DISC-TYPE-REF, e.g. AR-WALL-L03-001)
2. IFC type assignment — typed classes (IfcWall, IfcColumn …) must have an
                        IfcRelDefinesByType relationship
3. Omniclass / classification — element must reference a classification via
                        IfcRelAssociatesClassification OR carry a pset whose
                        name contains "omniclass" or "classification"

All output is advisory.  Results are never written back to the model.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element

from .models import (
    IFCCheckRequest,
    IFCCheckSummary,
    IFCTypeIssue,
    NamingIssue,
    OmniclassIssue,
    Priority,
)

# Default naming pattern: 2-4 uppercase discipline code, hyphen, then alphanumeric + hyphens.
# Examples that pass:  AR-WALL-L03-001  ST-COL-GF-001  ME-DUCT-L01-001  FP-SPKR-003
# Examples that fail:  "wall 01"  "WALL_001"  "" (empty)  "unnamed"
_DEFAULT_NAMING_PATTERN = re.compile(r"^[A-Z]{2,4}(?:-[A-Z0-9]+)+$", re.IGNORECASE)

# IFC product classes for which a type assignment is mandatory in coordinated BIM.
_TYPED_CLASSES: frozenset[str] = frozenset(
    {
        "IfcWall",
        "IfcWallStandardCase",
        "IfcColumn",
        "IfcColumnStandardCase",
        "IfcBeam",
        "IfcBeamStandardCase",
        "IfcSlab",
        "IfcDoor",
        "IfcWindow",
        "IfcRoof",
        "IfcStair",
        "IfcRamp",
        "IfcCovering",
        "IfcCurtainWall",
        "IfcMember",
        "IfcFooting",
        "IfcPile",
    }
)

# IFC product classes excluded from all checks (containers / spaces).
_SKIP_CLASSES: frozenset[str] = frozenset(
    {"IfcProject", "IfcSite", "IfcBuilding", "IfcBuildingStorey", "IfcSpace", "IfcZone"}
)


def _classification_psets(element: ifcopenshell.entity_instance) -> bool:
    """Return True if the element has a pset hinting at Omniclass or classification."""
    psets = ifcopenshell.util.element.get_psets(element)
    return any(
        "omniclass" in k.lower() or "classification" in k.lower() for k in psets
    )


def _has_ifc_classification(element: ifcopenshell.entity_instance, model: ifcopenshell.file) -> bool:
    """Return True if the model links this element to an IfcClassificationReference."""
    for rel in model.by_type("IfcRelAssociatesClassification"):
        if element in rel.RelatedObjects:
            return True
    return False


class IFCChecker:
    """Validate naming convention, IFC type, and Omniclass for every IfcProduct."""

    def check(self, request: IFCCheckRequest) -> IFCCheckSummary:
        path = Path(request.file_path)
        if not path.exists():
            raise FileNotFoundError(f"IFC file not found: {path}")

        model = ifcopenshell.open(str(path))
        pattern = (
            re.compile(request.naming_pattern, re.IGNORECASE)
            if request.naming_pattern
            else _DEFAULT_NAMING_PATTERN
        )

        # Resolve project name from IfcProject entity
        project_name = "Unknown Project"
        projects = model.by_type("IfcProject")
        if projects:
            project_name = projects[0].Name or project_name

        ifc_schema = model.schema  # e.g. "IFC4", "IFC2X3"

        products = [
            e for e in model.by_type("IfcProduct")
            if not any(e.is_a(skip) for skip in _SKIP_CLASSES)
        ]

        naming_issues: list[NamingIssue] = []
        type_issues: list[IFCTypeIssue] = []
        omniclass_issues: list[OmniclassIssue] = []

        type_eligible = 0

        for element in products:
            eid = str(element.id())
            eclass = element.is_a()
            name: str = element.Name or ""

            # ── Naming convention ─────────────────────────────────────────────
            if not name:
                naming_issues.append(
                    NamingIssue(
                        element_id=eid,
                        element_class=eclass,
                        name="(empty)",
                        issue="Element has no Name. All BIM objects must be named.",
                        severity=Priority.HIGH,
                    )
                )
            elif not pattern.match(name):
                naming_issues.append(
                    NamingIssue(
                        element_id=eid,
                        element_class=eclass,
                        name=name,
                        issue=(
                            f"'{name}' does not match the naming convention. "
                            "Expected format: [DISC]-[TYPE]-[REF], e.g. AR-WALL-L03-001."
                        ),
                        severity=Priority.MEDIUM,
                    )
                )

            # ── IFC type assignment ───────────────────────────────────────────
            if eclass in _TYPED_CLASSES:
                type_eligible += 1
                defining_type = ifcopenshell.util.element.get_type(element)
                if defining_type is None:
                    type_issues.append(
                        IFCTypeIssue(
                            element_id=eid,
                            element_class=eclass,
                            name=name,
                            issue=(
                                f"{eclass} has no IfcRelDefinesByType. "
                                "All architectural and structural elements must reference a type object."
                            ),
                        )
                    )

            # ── Omniclass / classification ────────────────────────────────────
            if request.omniclass_required:
                if not (
                    _classification_psets(element)
                    or _has_ifc_classification(element, model)
                ):
                    omniclass_issues.append(
                        OmniclassIssue(
                            element_id=eid,
                            element_class=eclass,
                            name=name,
                            issue=(
                                "No Omniclass or IfcClassificationReference found. "
                                "Assign classification before model coordination."
                            ),
                        )
                    )

        total = len(products)
        naming_pass = total - len(naming_issues)
        type_pass = type_eligible - len(type_issues)
        omniclass_pass = total - len(omniclass_issues)

        # Overall compliance: average of the three check pass rates
        scores = [naming_pass / total if total else 1.0]
        if type_eligible:
            scores.append(type_pass / type_eligible)
        if request.omniclass_required:
            scores.append(omniclass_pass / total if total else 1.0)
        overall = round(sum(scores) / len(scores) * 100, 1)

        return IFCCheckSummary(
            file_path=str(path),
            project_name=project_name,
            ifc_schema=ifc_schema,
            total_elements=total,
            naming_pass=naming_pass,
            naming_fail=len(naming_issues),
            type_eligible=type_eligible,
            type_pass=type_pass,
            type_fail=len(type_issues),
            omniclass_pass=omniclass_pass,
            omniclass_fail=len(omniclass_issues),
            overall_compliance_pct=overall,
            naming_issues=naming_issues,
            type_issues=type_issues,
            omniclass_issues=omniclass_issues,
            generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )


ifc_checker = IFCChecker()
