from __future__ import annotations

import importlib.util
from pathlib import Path


def _plot_mod():
    path = (
        Path(__file__).resolve().parents[1]
        / "skills"
        / "tune-hfss-antenna"
        / "scripts"
        / "plot_s11.py"
    )
    spec = importlib.util.spec_from_file_location("plot_s11", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_strongest_s11_peak_picks_bump_not_band_edge() -> None:
    plot_s11 = _plot_mod()
    freqs = [float(i) for i in range(1, 12)]
    dbs = [-14.0, -13.5, -13.0, -12.5, -11.0, -10.2, -11.5, -13.0, -14.0, -14.2, -14.5]
    peak = plot_s11.strongest_s11_peak(freqs, dbs)
    assert peak is not None
    assert peak[0] == 6.0
    assert peak[1] == -10.2


def test_strongest_s11_peak_none_on_monotonic() -> None:
    plot_s11 = _plot_mod()
    freqs = [1.0, 2.0, 3.0, 4.0]
    dbs = [-20.0, -18.0, -16.0, -14.0]
    assert plot_s11.strongest_s11_peak(freqs, dbs) is None
