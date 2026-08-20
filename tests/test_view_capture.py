"""view_capture hides air boxes before FitAll (no live AEDT)."""

from __future__ import annotations

from pathlib import Path

from hfss_mcp.live import is_airbox_object_name, view_capture_script


def test_airbox_name_detection() -> None:
    assert is_airbox_object_name("AirBox")
    assert is_airbox_object_name("air_box")
    assert is_airbox_object_name("RadiationBox")
    assert not is_airbox_object_name("Substrate")
    assert not is_airbox_object_name("Patch")
    assert not is_airbox_object_name("pair")


def test_script_hides_then_fits_then_exports() -> None:
    src = view_capture_script(Path("C:/tmp/view.jpg"), orientation="Top")
    hide_at = src.find("vis(hidden, False)")
    fit_at = src.find("oEditor.FitAll()")
    export_at = src.find("ExportModelImageToFile")
    restore_at = src.find("vis(hidden, True)")
    assert hide_at != -1 and fit_at != -1 and export_at != -1 and restore_at != -1
    assert hide_at < fit_at < export_at < restore_at
    assert "oEditor.Hide(" in src
    assert "oEditor.Show(" in src
    assert "'NAME:Show'" not in src
    assert "Geometry3DAttributeTab" not in src
    assert "ShowRegion:=', False" in src
    assert "is_airbox" in src
