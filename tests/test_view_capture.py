"""view_hide / view_capture scripts (no live AEDT)."""

from __future__ import annotations

from pathlib import Path

from hfss_mcp.live import is_airbox_object_name, view_capture_script, view_visibility_script


def test_airbox_name_detection() -> None:
    assert is_airbox_object_name("AirBox")
    assert is_airbox_object_name("air_box")
    assert is_airbox_object_name("RadiationBox")
    assert not is_airbox_object_name("Substrate")
    assert not is_airbox_object_name("Patch")
    assert not is_airbox_object_name("pair")


def test_capture_does_not_auto_hide_airbox() -> None:
    src = view_capture_script(Path("C:/tmp/view.jpg"), orientation="top")
    assert "is_airbox" not in src
    assert "ExportModelImageToFile" in src
    assert "Selections" in src


def test_capture_warmup_forces_fresh_frame() -> None:
    src = view_capture_script(Path("C:/tmp/view.jpg"), orientation="isometric")
    warm = src.find("ExportModelImageToFile(warm_name, 64, 40")
    real = src.find("ExportModelImageToFile(file_name, int(width), int(height)")
    assert warm != -1 and real != -1 and warm < real
    # the warm-up shot must use a DIFFERENT orientation than the real one
    assert "warm_orientation = 'top'" in src
    src_top = view_capture_script(Path("C:/tmp/view.jpg"), orientation="top")
    assert "warm_orientation = 'isometric'" in src_top


def test_capture_fit_uses_export_selections() -> None:
    src = view_capture_script(Path("C:/tmp/view.jpg"), fit=["cop1", "feedb"])
    assert 'keep = ["cop1", "feedb"]' in src or "keep = ['cop1', 'feedb']" in src
    # isolation is export-time Selections + FitToSelections, not visibility hacks
    assert "'Selections:=', sel_text" in src
    assert "'FitToSelections:=', fit_sel" in src
    assert "fit_sel = 'True' if selection else ''" in src
    assert "if keep:" in src
    assert "selection = [n for n in keep if n in all_names]" in src
    assert "oEditor.Hide(" not in src
    assert "FitAll" not in src
    # fewer-arg ExportModelImageToFile fallbacks are dead code; only 4-arg remains
    assert "for args in" not in src


def test_capture_excludes_persistent_hidden_from_selection() -> None:
    src = view_capture_script(Path("C:/tmp/view.jpg"), hidden=["Region", "gnd"])
    assert 'hidden = ["Region", "gnd"]' in src or "hidden = ['Region', 'gnd']" in src
    assert "selection = [n for n in all_names if n not in hidden]" in src


def test_visibility_script_is_pure_bookkeeping() -> None:
    src = view_visibility_script(names=["Region", "gnd"], show=False)
    assert "want =" in src
    assert "all_objects = False" in src
    assert "result['names'] = targets" in src
    assert "result['missing'] = missing" in src
    # no GUI mutation: no transparency fakery, no nonexistent Hide/Show
    assert "ChangeProperty" not in src
    assert "Transparent" not in src
    assert "oEditor.Hide(" not in src
    assert "oEditor.Show(" not in src
