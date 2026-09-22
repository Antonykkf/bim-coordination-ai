"""
Tests for IFCChecker.

Uses an in-memory IFC4 model — no file on disk required.
The checker logic is tested via a temporary file written to a temp directory
because ifcopenshell.open() requires a file path.
"""

import tempfile
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid
import pytest

from bim_coordination_ai.ifc_checker import IFCChecker, _DEFAULT_NAMING_PATTERN
from bim_coordination_ai.models import IFCCheckRequest, Priority


# ── Helpers ───────────────────────────────────────────────────────────────────

def _new_model() -> ifcopenshell.file:
    model = ifcopenshell.file(schema="IFC4")
    model.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="TestProject")
    return model


def _add_wall(model: ifcopenshell.file, name: str) -> ifcopenshell.entity_instance:
    return model.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name=name)


def _add_column(model: ifcopenshell.file, name: str) -> ifcopenshell.entity_instance:
    return model.create_entity("IfcColumn", GlobalId=ifcopenshell.guid.new(), Name=name)


def _save_tmp(model: ifcopenshell.file) -> Path:
    """Write model to a temp file and return the path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
    tmp.close()
    model.write(tmp.name)
    return Path(tmp.name)


def _check(model: ifcopenshell.file, **kwargs) -> object:
    path = _save_tmp(model)
    try:
        checker = IFCChecker()
        req = IFCCheckRequest(file_path=str(path), **kwargs)
        return checker.check(req)
    finally:
        path.unlink(missing_ok=True)


# ── Naming convention tests ───────────────────────────────────────────────────

def test_default_pattern_passes_valid_names():
    assert _DEFAULT_NAMING_PATTERN.match("AR-WALL-L03-001")
    assert _DEFAULT_NAMING_PATTERN.match("ST-COL-GF-001")
    assert _DEFAULT_NAMING_PATTERN.match("ME-DUCT-L01-001")
    assert _DEFAULT_NAMING_PATTERN.match("FP-SPKR-003")


def test_default_pattern_rejects_invalid_names():
    assert not _DEFAULT_NAMING_PATTERN.match("wall 001")
    assert not _DEFAULT_NAMING_PATTERN.match("WALL_001")
    assert not _DEFAULT_NAMING_PATTERN.match("unnamed")
    assert not _DEFAULT_NAMING_PATTERN.match("")
    assert not _DEFAULT_NAMING_PATTERN.match("AR")  # no hyphen/type


def test_compliant_names_produce_no_naming_issues():
    model = _new_model()
    _add_wall(model, "AR-WALL-L03-001")
    _add_wall(model, "AR-WALL-L03-002")
    result = _check(model, omniclass_required=False)
    assert result.naming_fail == 0


def test_empty_name_is_high_severity():
    model = _new_model()
    _add_wall(model, "")
    result = _check(model, omniclass_required=False)
    assert result.naming_fail == 1
    assert result.naming_issues[0].severity == Priority.HIGH


def test_bad_name_is_medium_severity():
    model = _new_model()
    _add_wall(model, "wall 001 bad name")
    result = _check(model, omniclass_required=False)
    assert result.naming_fail == 1
    assert result.naming_issues[0].severity == Priority.MEDIUM


def test_custom_pattern_overrides_default():
    model = _new_model()
    _add_wall(model, "WALL_001")  # fails default but passes custom
    result = _check(model, naming_pattern=r"^WALL_\d+$", omniclass_required=False)
    assert result.naming_fail == 0


# ── IFC type assignment tests ─────────────────────────────────────────────────

def test_wall_without_type_raises_type_issue():
    model = _new_model()
    _add_wall(model, "AR-WALL-001")
    result = _check(model, omniclass_required=False)
    assert result.type_eligible == 1
    assert result.type_fail == 1


def test_wall_with_type_passes_type_check():
    model = _new_model()
    wall = _add_wall(model, "AR-WALL-001")
    wall_type = model.create_entity(
        "IfcWallType", GlobalId=ifcopenshell.guid.new(), Name="WT-BASIC-001"
    )
    model.create_entity(
        "IfcRelDefinesByType",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=[wall],
        RelatingType=wall_type,
    )
    result = _check(model, omniclass_required=False)
    assert result.type_fail == 0


def test_column_without_type_fails():
    model = _new_model()
    _add_column(model, "ST-COL-001")
    result = _check(model, omniclass_required=False)
    assert result.type_fail >= 1


# ── Omniclass / classification tests ─────────────────────────────────────────

def test_missing_omniclass_raises_issue_when_required():
    model = _new_model()
    _add_wall(model, "AR-WALL-001")
    result = _check(model, omniclass_required=True)
    assert result.omniclass_fail >= 1


def test_omniclass_not_checked_when_disabled():
    model = _new_model()
    _add_wall(model, "AR-WALL-001")
    result = _check(model, omniclass_required=False)
    assert result.omniclass_fail == 0


def test_element_with_classification_pset_passes():
    model = _new_model()
    wall = _add_wall(model, "AR-WALL-001")
    pset = model.create_entity(
        "IfcPropertySet",
        GlobalId=ifcopenshell.guid.new(),
        Name="Pset_OmniclassReference",
        HasProperties=[],
    )
    model.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=[wall],
        RelatingPropertyDefinition=pset,
    )
    result = _check(model, omniclass_required=True)
    # The wall now carries a pset with "omniclass" in the name → should pass
    # (type issue may still exist but omniclass_fail should be 0)
    assert result.omniclass_fail == 0


# ── Summary metrics ───────────────────────────────────────────────────────────

def test_total_elements_counts_only_products():
    model = _new_model()
    # IfcProject is not a product — should not be counted
    _add_wall(model, "AR-WALL-001")
    _add_wall(model, "AR-WALL-002")
    result = _check(model, omniclass_required=False)
    assert result.total_elements == 2


def test_overall_compliance_100_when_all_pass():
    model = _new_model()
    wall = _add_wall(model, "AR-WALL-001")
    wall_type = model.create_entity(
        "IfcWallType", GlobalId=ifcopenshell.guid.new(), Name="WT-BASIC-001"
    )
    model.create_entity(
        "IfcRelDefinesByType",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=[wall],
        RelatingType=wall_type,
    )
    result = _check(model, omniclass_required=False)
    assert result.naming_fail == 0
    assert result.type_fail == 0
    assert result.overall_compliance_pct == 100.0


def test_project_name_extracted():
    model = _new_model()
    _add_wall(model, "AR-WALL-001")
    result = _check(model, omniclass_required=False)
    assert result.project_name == "TestProject"
