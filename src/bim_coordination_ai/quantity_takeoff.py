"""
5D BIM Quantity Take-Off service.

Extracts quantities from IFC BaseQuantities (Qto_* property sets) and
optionally multiplies by user-supplied cost rates to produce a 5D BIM
cost summary.

Quantity extraction strategy (in priority order):
  1. Qto_* property sets already embedded in the IFC (most reliable)
  2. Simple count = 1 for countable elements with no geometry quantities
  3. Element is skipped if it produces no meaningful quantity

Discipline mapping follows the standard BIM discipline split:
  STRUCTURE  → IfcColumn, IfcBeam, IfcSlab (structural), IfcMember, IfcFooting, IfcPile
  ARCHITECTURE → IfcWall, IfcCurtainWall, IfcDoor, IfcWindow, IfcRoof, IfcCovering, IfcSlab (floor)
  MEP        → IfcDuctSegment, IfcPipeSegment, IfcCableCarrierSegment, IfcFlowTerminal, IfcFlowFitting
  CIVIL      → IfcCivilElement, IfcEarthworksCut, IfcEarthworksFill
  FIRE       → IfcFireSuppressionTerminal, elements with "fire" in type name
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element

from .models import (
    CostRate,
    Discipline,
    QTORequest,
    QTOResult,
    QTOSummary,
    QuantityItem,
)

# ── Discipline mapping ────────────────────────────────────────────────────────

_DISCIPLINE_MAP: dict[str, Discipline] = {
    "IfcColumn": Discipline.STRUCTURE,
    "IfcColumnStandardCase": Discipline.STRUCTURE,
    "IfcBeam": Discipline.STRUCTURE,
    "IfcBeamStandardCase": Discipline.STRUCTURE,
    "IfcMember": Discipline.STRUCTURE,
    "IfcFooting": Discipline.STRUCTURE,
    "IfcPile": Discipline.STRUCTURE,
    "IfcWall": Discipline.ARCHITECTURE,
    "IfcWallStandardCase": Discipline.ARCHITECTURE,
    "IfcCurtainWall": Discipline.ARCHITECTURE,
    "IfcDoor": Discipline.ARCHITECTURE,
    "IfcWindow": Discipline.ARCHITECTURE,
    "IfcRoof": Discipline.ARCHITECTURE,
    "IfcCovering": Discipline.ARCHITECTURE,
    "IfcStair": Discipline.ARCHITECTURE,
    "IfcRamp": Discipline.ARCHITECTURE,
    "IfcDuctSegment": Discipline.MEP,
    "IfcDuctFitting": Discipline.MEP,
    "IfcPipeSegment": Discipline.MEP,
    "IfcPipeFitting": Discipline.MEP,
    "IfcCableCarrierSegment": Discipline.MEP,
    "IfcCableSegment": Discipline.MEP,
    "IfcFlowTerminal": Discipline.MEP,
    "IfcFlowFitting": Discipline.MEP,
    "IfcAirTerminal": Discipline.MEP,
    "IfcFireSuppressionTerminal": Discipline.FIRE,
    "IfcCivilElement": Discipline.CIVIL,
}

# ── Quantity extraction rules per IFC class ───────────────────────────────────
# Each entry: (qto_pset_name, quantity_property, quantity_type, unit)
# quantity_type: "area" | "volume" | "count" | "length"

_QTO_RULES: dict[str, tuple[str, str, str, str]] = {
    "IfcWall":                ("Qto_WallBaseQuantities",        "NetSideArea",   "area",   "m2"),
    "IfcWallStandardCase":    ("Qto_WallBaseQuantities",        "NetSideArea",   "area",   "m2"),
    "IfcCurtainWall":         ("Qto_CurtainWallBaseQuantities", "GrossArea",     "area",   "m2"),
    "IfcSlab":                ("Qto_SlabBaseQuantities",        "GrossArea",     "area",   "m2"),
    "IfcRoof":                ("Qto_RoofBaseQuantities",        "GrossArea",     "area",   "m2"),
    "IfcCovering":            ("Qto_CoveringBaseQuantities",    "GrossArea",     "area",   "m2"),
    "IfcColumn":              ("Qto_ColumnBaseQuantities",      "GrossVolume",   "volume", "m3"),
    "IfcColumnStandardCase":  ("Qto_ColumnBaseQuantities",      "GrossVolume",   "volume", "m3"),
    "IfcBeam":                ("Qto_BeamBaseQuantities",        "GrossVolume",   "volume", "m3"),
    "IfcBeamStandardCase":    ("Qto_BeamBaseQuantities",        "GrossVolume",   "volume", "m3"),
    "IfcMember":              ("Qto_MemberBaseQuantities",      "GrossVolume",   "volume", "m3"),
    "IfcFooting":             ("Qto_FootingBaseQuantities",     "GrossVolume",   "volume", "m3"),
    "IfcPile":                ("Qto_PileBaseQuantities",        "GrossVolume",   "volume", "m3"),
    "IfcDoor":                ("Qto_DoorBaseQuantities",        "Width",         "count",  "nr"),
    "IfcWindow":              ("Qto_WindowBaseQuantities",      "Width",         "count",  "nr"),
    "IfcStair":               ("Qto_StairBaseQuantities",       "GrossVolume",   "volume", "m3"),
    "IfcRamp":                ("Qto_RampBaseQuantities",        "GrossVolume",   "volume", "m3"),
    "IfcDuctSegment":         ("Qto_DuctSegmentBaseQuantities", "Length",        "length", "m"),
    "IfcPipeSegment":         ("Qto_PipeSegmentBaseQuantities", "Length",        "length", "m"),
    "IfcCableCarrierSegment": ("Qto_CableCarrierSegmentBaseQuantities", "Length","length", "m"),
    "IfcCableSegment":        ("Qto_CableSegmentBaseQuantities","Length",        "length", "m"),
    "IfcFlowTerminal":        (None,                            None,            "count",  "nr"),
    "IfcAirTerminal":         (None,                            None,            "count",  "nr"),
    "IfcFireSuppressionTerminal": (None,                        None,            "count",  "nr"),
    "IfcCivilElement":        (None,                            None,            "count",  "nr"),
}

_COUNTABLE_CLASSES = frozenset(
    {"IfcDoor", "IfcWindow", "IfcFlowTerminal", "IfcAirTerminal",
     "IfcFireSuppressionTerminal", "IfcCivilElement"}
)

_SKIP_CLASSES = frozenset(
    {"IfcProject", "IfcSite", "IfcBuilding", "IfcBuildingStorey", "IfcSpace", "IfcZone"}
)

_FIRE_PATTERN = re.compile(r"fire|sprinkler|suppression", re.IGNORECASE)


def _get_storey(element: ifcopenshell.entity_instance) -> str:
    """Return the name of the containing building storey, if any."""
    container = ifcopenshell.util.element.get_container(element)
    if container is None:
        return ""
    if container.is_a("IfcBuildingStorey"):
        return container.Name or ""
    return ""


def _extract_quantity(
    element: ifcopenshell.entity_instance,
    eclass: str,
) -> tuple[float, str, str] | None:
    """
    Return (value, unit, quantity_type) for the element, or None if not extractable.
    """
    rule = _QTO_RULES.get(eclass)
    if rule is None:
        return None

    qto_name, qty_prop, qty_type, unit = rule

    # Countable elements with no geometry rule
    if qto_name is None:
        return 1.0, unit, qty_type

    # Doors and windows: report as count (1 per element)
    if qty_type == "count":
        return 1.0, unit, qty_type

    # Try to find the Qto_ property set
    qtos = ifcopenshell.util.element.get_psets(element, qtos_only=True)
    qto = qtos.get(qto_name)
    if qto and qty_prop in qto:
        value = qto[qty_prop]
        if isinstance(value, (int, float)) and value > 0:
            return float(value), unit, qty_type

    # Fallback: scan all Qtos for any matching quantity name
    for _name, props in qtos.items():
        if isinstance(props, dict) and qty_prop in props:
            value = props[qty_prop]
            if isinstance(value, (int, float)) and value > 0:
                return float(value), unit, qty_type

    return None


def _resolve_discipline(element: ifcopenshell.entity_instance, eclass: str) -> Discipline:
    disc = _DISCIPLINE_MAP.get(eclass)
    if disc:
        return disc
    # Heuristic: check object type name for fire suppression
    obj_type = (element.ObjectType or "") if hasattr(element, "ObjectType") else ""
    if _FIRE_PATTERN.search(obj_type):
        return Discipline.FIRE
    return Discipline.UNKNOWN


class QTOService:
    """Extract 5D BIM quantities from an IFC file."""

    def extract(self, request: QTORequest) -> QTOResult:
        path = Path(request.file_path)
        if not path.exists():
            raise FileNotFoundError(f"IFC file not found: {path}")

        model = ifcopenshell.open(str(path))

        project_name = "Unknown Project"
        projects = model.by_type("IfcProject")
        if projects:
            project_name = projects[0].Name or project_name

        # Build rate lookup: class → (rate, unit)
        rates: dict[str, CostRate] = {r.element_class: r for r in request.rates}

        items: list[QuantityItem] = []

        for element in model.by_type("IfcProduct"):
            if any(element.is_a(skip) for skip in _SKIP_CLASSES):
                continue

            eclass = element.is_a()
            result = _extract_quantity(element, eclass)
            if result is None:
                continue

            qty_value, unit, qty_type = result
            discipline = _resolve_discipline(element, eclass)
            storey = _get_storey(element)
            name = element.Name or f"{eclass}-{element.id()}"

            cost_rate = rates.get(eclass)
            rate_val = cost_rate.rate if cost_rate else None
            cost_val = round(qty_value * rate_val, 2) if rate_val is not None else None

            items.append(
                QuantityItem(
                    element_class=eclass,
                    element_id=str(element.id()),
                    name=name,
                    storey=storey,
                    discipline=discipline,
                    quantity_type=qty_type,
                    quantity_value=round(qty_value, 4),
                    unit=unit,
                    rate=rate_val,
                    cost=cost_val,
                )
            )

        # Aggregate by element class
        class_totals: dict[str, dict] = defaultdict(
            lambda: {
                "count": 0,
                "total_quantity": 0.0,
                "total_cost": None,  # None until a rate is applied for this class
                "unit": "",
                "qty_type": "",
                "discipline": Discipline.UNKNOWN,
            }
        )
        for item in items:
            ct = class_totals[item.element_class]
            ct["count"] += 1
            ct["total_quantity"] += item.quantity_value
            ct["unit"] = item.unit
            ct["qty_type"] = item.quantity_type
            ct["discipline"] = item.discipline
            if item.cost is not None:
                ct["total_cost"] = (ct["total_cost"] or 0.0) + item.cost

        summary: list[QTOSummary] = []
        grand_total = 0.0
        any_cost = False

        for eclass, ct in sorted(class_totals.items()):
            class_cost = round(ct["total_cost"], 2) if ct["total_cost"] is not None else None
            if class_cost is not None:
                grand_total += ct["total_cost"]
                any_cost = True
            summary.append(
                QTOSummary(
                    element_class=eclass,
                    discipline=ct["discipline"],
                    count=ct["count"],
                    total_quantity=round(ct["total_quantity"], 4),
                    unit=ct["unit"],
                    quantity_type=ct["qty_type"],
                    total_cost=class_cost,
                )
            )

        from datetime import timezone
        return QTOResult(
            file_path=str(path),
            project_name=project_name,
            currency=request.currency,
            items=items,
            summary=summary,
            grand_total_cost=round(grand_total, 2) if any_cost else None,
            generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )


qto_service = QTOService()
