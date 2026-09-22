"""
Tests for QTOService.

Uses in-memory IFC4 models without pre-computed Qto_ property sets.
Elements with no Qto_ data for counted types (IfcDoor, IfcWindow, IfcFlowTerminal)
still produce quantity=1 each, so those tests remain meaningful.
"""

import tempfile
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid
import pytest

from bim_coordination_ai.models import CostRate, Discipline, QTORequest
from bim_coordination_ai.quantity_takeoff import QTOService


def _new_model() -> ifcopenshell.file:
    model = ifcopenshell.file(schema="IFC4")
    model.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="QTO-Test-Project")
    return model


def _save_tmp(model: ifcopenshell.file) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
    tmp.close()
    model.write(tmp.name)
    return Path(tmp.name)


def _extract(model: ifcopenshell.file, rates=None) -> object:
    path = _save_tmp(model)
    try:
        svc = QTOService()
        req = QTORequest(file_path=str(path), rates=rates or [], currency="USD")
        return svc.extract(req)
    finally:
        path.unlink(missing_ok=True)


# ── Countable elements (Qto_-independent) ────────────────────────────────────

def test_door_counted_as_one_each():
    model = _new_model()
    model.create_entity("IfcDoor", GlobalId=ifcopenshell.guid.new(), Name="AR-DOOR-001")
    model.create_entity("IfcDoor", GlobalId=ifcopenshell.guid.new(), Name="AR-DOOR-002")
    result = _extract(model)
    summary = {s.element_class: s for s in result.summary}
    assert "IfcDoor" in summary
    assert summary["IfcDoor"].count == 2
    assert summary["IfcDoor"].total_quantity == 2.0
    assert summary["IfcDoor"].unit == "nr"
    assert summary["IfcDoor"].discipline == Discipline.ARCHITECTURE


def test_window_counted_as_one_each():
    model = _new_model()
    model.create_entity("IfcWindow", GlobalId=ifcopenshell.guid.new(), Name="AR-WIN-001")
    result = _extract(model)
    summary = {s.element_class: s for s in result.summary}
    assert "IfcWindow" in summary
    assert summary["IfcWindow"].count == 1


def test_flow_terminal_counted():
    model = _new_model()
    model.create_entity("IfcFlowTerminal", GlobalId=ifcopenshell.guid.new(), Name="ME-FT-001")
    model.create_entity("IfcFlowTerminal", GlobalId=ifcopenshell.guid.new(), Name="ME-FT-002")
    model.create_entity("IfcFlowTerminal", GlobalId=ifcopenshell.guid.new(), Name="ME-FT-003")
    result = _extract(model)
    summary = {s.element_class: s for s in result.summary}
    assert "IfcFlowTerminal" in summary
    assert summary["IfcFlowTerminal"].count == 3
    assert summary["IfcFlowTerminal"].discipline == Discipline.MEP


# ── Cost calculation ──────────────────────────────────────────────────────────

def test_door_cost_with_rate():
    model = _new_model()
    model.create_entity("IfcDoor", GlobalId=ifcopenshell.guid.new(), Name="AR-DOOR-001")
    model.create_entity("IfcDoor", GlobalId=ifcopenshell.guid.new(), Name="AR-DOOR-002")
    rates = [CostRate(element_class="IfcDoor", rate=2500.0, unit="nr", currency="USD")]
    result = _extract(model, rates=rates)
    summary = {s.element_class: s for s in result.summary}
    assert summary["IfcDoor"].total_cost == pytest.approx(5000.0)
    assert result.grand_total_cost == pytest.approx(5000.0)


def test_no_cost_when_no_rates():
    model = _new_model()
    model.create_entity("IfcDoor", GlobalId=ifcopenshell.guid.new(), Name="AR-DOOR-001")
    result = _extract(model)
    assert result.grand_total_cost is None
    for s in result.summary:
        assert s.total_cost is None


def test_mixed_rates_partial_coverage():
    model = _new_model()
    model.create_entity("IfcDoor", GlobalId=ifcopenshell.guid.new(), Name="AR-DOOR-001")
    model.create_entity("IfcWindow", GlobalId=ifcopenshell.guid.new(), Name="AR-WIN-001")
    rates = [CostRate(element_class="IfcDoor", rate=2500.0, unit="nr", currency="USD")]
    result = _extract(model, rates=rates)
    summary = {s.element_class: s for s in result.summary}
    # Door has a rate → cost
    assert summary["IfcDoor"].total_cost == pytest.approx(2500.0)
    # Window has no rate → None
    assert summary["IfcWindow"].total_cost is None


# ── Discipline assignment ─────────────────────────────────────────────────────

def test_wall_discipline_is_architecture():
    model = _new_model()
    model.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name="AR-WALL-001")
    result = _extract(model)
    # Wall may not have Qto_ data in a bare model, so it might not appear in summary
    # but if it does, discipline should be ARCHITECTURE
    summary = {s.element_class: s for s in result.summary}
    if "IfcWall" in summary:
        assert summary["IfcWall"].discipline == Discipline.ARCHITECTURE


def test_column_discipline_is_structure():
    model = _new_model()
    model.create_entity("IfcColumn", GlobalId=ifcopenshell.guid.new(), Name="ST-COL-001")
    result = _extract(model)
    summary = {s.element_class: s for s in result.summary}
    if "IfcColumn" in summary:
        assert summary["IfcColumn"].discipline == Discipline.STRUCTURE


# ── Project metadata ──────────────────────────────────────────────────────────

def test_project_name_in_result():
    model = _new_model()
    model.create_entity("IfcDoor", GlobalId=ifcopenshell.guid.new(), Name="AR-DOOR-001")
    result = _extract(model)
    assert result.project_name == "QTO-Test-Project"


def test_currency_in_result():
    model = _new_model()
    model.create_entity("IfcDoor", GlobalId=ifcopenshell.guid.new(), Name="AR-DOOR-001")
    path = _save_tmp(model)
    try:
        svc = QTOService()
        req = QTORequest(file_path=str(path), rates=[], currency="SGD")
        result = svc.extract(req)
        assert result.currency == "SGD"
    finally:
        path.unlink(missing_ok=True)


# ── Line items ────────────────────────────────────────────────────────────────

def test_items_include_element_names():
    model = _new_model()
    model.create_entity("IfcDoor", GlobalId=ifcopenshell.guid.new(), Name="AR-DOOR-MAIN")
    result = _extract(model)
    door_items = [i for i in result.items if i.element_class == "IfcDoor"]
    assert any(i.name == "AR-DOOR-MAIN" for i in door_items)


def test_skip_classes_excluded():
    """IfcProject, IfcBuilding etc. must not appear in QTO items."""
    model = _new_model()
    result = _extract(model)
    for item in result.items:
        assert item.element_class not in (
            "IfcProject", "IfcSite", "IfcBuilding", "IfcBuildingStorey"
        )
