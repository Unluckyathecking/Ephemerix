"""The shared Target type and tolerant targets.json loading."""

import json
from pathlib import Path

import pytest

from pxs import sources, spherex
from pxs.target import Target, TargetError, load_targets

FULL_ENTRY = {
    "slug": "eps-ind-b", "name": "Epsilon Indi Ba/Bb", "blurb": "A nearby T dwarf pair.",
    "ra": 331.0764526, "dec": -56.7938121, "epoch": 2016.0,
    "pmra_masyr": 3981.977, "pmdec_masyr": -2466.832, "parallax_mas": 270.658,
    "known_type": "T1+T6", "known_type_ref": "King et al. 2010", "discovery_ref": "Scholz 2003",
    "w1_mag": None, "w2_mag": 11.1, "group": "brown dwarfs", "notes": "unresolved pair",
    "sources": ["https://gea.esac.esa.int/tap-server/tap/sync"],
    "something_new": {"nested": [1, 2]},
}


def test_one_target_type_shared_by_assembly_and_spherex() -> None:
    assert sources.Target is Target and spherex.Target is Target


def test_loads_all_seventeen_keys_and_ignores_unknown(tmp_path: Path) -> None:
    path = tmp_path / "targets.json"
    path.write_text(json.dumps([FULL_ENTRY]))
    (t,) = load_targets(path)
    assert (t.slug, t.known_type, t.known_type_ref, t.has_pm) == (
        "eps-ind-b", "T1+T6", "King et al. 2010", True)


def test_target_validates_at_construction() -> None:
    with pytest.raises(ValueError):
        Target("x", 360.0, 0.0, 2000.0)
    with pytest.raises(ValueError):
        Target("x", 1.0, 0.0, 2000.0, pmra_masyr=float("nan"), pmdec_masyr=0.0)
    with pytest.raises(ValueError):
        Target("x", 1.0, 0.0, 2000.0, fov_arcsec=0.0)


def test_bad_string_field_names_the_entry(tmp_path: Path) -> None:
    path = tmp_path / "targets.json"
    path.write_text(json.dumps([{**FULL_ENTRY, "known_type": 7}]))
    with pytest.raises(TargetError, match=r"entry 0 .*known_type"):
        load_targets(path)
