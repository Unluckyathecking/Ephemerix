"""The S/N and blend gate in front of the template match."""

from pxs.typegate import BLEND_REASON, MIN_DETECTED, detecting_arrays, faint_reason, vet


def _spec(n: int, detectors: int, snr: float, wl0: float = 1.0) -> dict:
    pts = [{"wl_um": wl0 + 0.05 * i, "flux": snr * 0.1, "err": 0.1, "flagged": False,
            "detector": 1 + i % detectors} for i in range(n)]
    return {"id": "spx-all", "points": pts}


MATCH = {"spectrum_id": "spx-all", "best": {"type": "T8"}}


def test_a_well_detected_spectrum_passes() -> None:
    spec = _spec(40, 6, 10.0)
    assert faint_reason(spec) is None
    assert vet(MATCH, [spec], blended=False) == (MATCH, [])


def test_two_arrays_are_enough_one_is_not() -> None:
    # A cold brown dwarf seen only at 3.8-5.0 um (D5 and D6), like UGPS 0722 or WISE 0855.
    assert faint_reason(_spec(30, 2, 10.0, wl0=3.8)) is None
    one = _spec(30, 1, 10.0, wl0=4.4)
    assert "only 1 of its six wavelength ranges" in faint_reason(one)
    assert vet(MATCH, [one], blended=False)[0] is None


def test_scattered_peaks_do_not_make_an_array_detect() -> None:
    # D5, D6 detected; D1-D4 each have 2 of 10 points at S/N >= 3 (noise or a neighbour).
    pts = [{"wl_um": 4.0 + 0.01 * i, "flux": 1.0, "err": 0.1, "flagged": False,
            "detector": 5 + i % 2} for i in range(30)]
    for d in range(1, 5):
        pts += [{"wl_um": 0.8 * d + 0.01 * i, "flux": 0.5 if i < 2 else 0.05, "err": 0.1,
                 "flagged": False, "detector": d} for i in range(10)]
    assert detecting_arrays({"id": "x", "points": pts}) == [5, 6]
    only5 = [p for p in pts if p["detector"] != 6]
    assert detecting_arrays({"id": "x", "points": only5}) == [5]
    assert "only 1 of its six" in faint_reason({"id": "x", "points": only5})


def test_too_few_clear_points_is_gated() -> None:
    few = _spec(MIN_DETECTED - 1, 6, 10.0)
    assert f"at only {MIN_DETECTED - 1} wavelengths" in faint_reason(few)


def test_noise_is_not_detection() -> None:
    assert "no clear detection" in faint_reason(_spec(60, 6, 2.0))


def test_blend_blocks_the_match_with_a_reason() -> None:
    assert vet(MATCH, [_spec(40, 6, 10.0)], blended=True) == (None, [BLEND_REASON])
    faint_and_blended = vet(MATCH, [_spec(40, 1, 10.0, wl0=3.8)], blended=True)
    assert faint_and_blended[0] is None and len(faint_and_blended[1]) == 2
    assert vet(None, [], blended=True) == (None, [])


def test_contamination_by_a_brighter_source_blocks_the_match() -> None:
    why = "The spectrum is not classified because a brighter catalogued source ..."
    assert vet(MATCH, [_spec(40, 6, 10.0)], blended=False, contaminated=why) == (None, [why])


def test_no_type_for_a_target_found_in_no_image() -> None:
    from pxs.typegate import UNSEEN_REASON

    assert vet(MATCH, [_spec(40, 6, 10.0)], blended=False, seen=False) == (None, [UNSEEN_REASON])
    assert vet(MATCH, [_spec(40, 6, 10.0)], blended=False, seen=True) == (MATCH, [])


def test_a_caution_keeps_the_type_but_marks_it_provisional() -> None:
    why = "A catalogued source 4.9 arcsec away may contribute ...; treat the type as provisional."
    match, notes = vet(MATCH, [_spec(40, 6, 10.0)], blended=False, caution=why)
    assert match == {**MATCH, "provisional": why, "provisional_kind": "neighbour"}
    assert notes == [why] and "provisional" not in MATCH
    refused = vet(MATCH, [_spec(40, 6, 10.0)], blended=True, caution=why)
    assert refused == (None, [BLEND_REASON])  # a refusal wins; no caution shown


# --- faint spectra: typed from the whole fit, or left out with a true reason ---------------

FAINT = _spec(60, 6, 2.0)  # no point reaches S/N 3: fails the count
BD = {"spectrum_id": "spx-all", "best": {"type": "T8"}, "class": "brown dwarf",
      "verdict": "Consistent with a cold brown dwarf, type T6 to Y0 (best match T8)."}


def test_a_faint_spectrum_with_a_decisive_fit_is_typed_as_provisional() -> None:
    from pxs.typegate import FAINT_MIN_SIGMA, FAINT_NOTE

    fit = {**BD, "detection_sigma": FAINT_MIN_SIGMA}
    match, notes = vet(fit, [FAINT], blended=False)
    assert match == {**fit, "provisional": FAINT_NOTE, "provisional_kind": "faint"}
    assert notes == [FAINT_NOTE]
    assert "provisional" in FAINT_NOTE and "two subtypes" in FAINT_NOTE


def test_a_faint_spectrum_below_the_fit_significance_keeps_the_count_sentence() -> None:
    from pxs.typegate import FAINT_MIN_SIGMA

    weak = {**BD, "detection_sigma": FAINT_MIN_SIGMA - 0.1}
    assert vet(weak, [FAINT], blended=False) == (None, [faint_reason(FAINT)])
    assert vet(BD, [FAINT], blended=False) == (None, [faint_reason(FAINT)])  # no significance


def test_a_faint_spectrum_with_an_undecided_fit_says_what_the_fit_found() -> None:
    verdict = ("Could be a brown dwarf (best match T8) or a dusty or young red source; "
               "the data cannot tell.")
    fit = {**BD, "class": "uncertain", "verdict": verdict, "detection_sigma": 14.0}
    match, notes = vet(fit, [FAINT], blended=False)
    assert match is None and len(notes) == 1
    assert "is not classified because" in notes[0] and notes[0].endswith(verdict)


def test_only_a_brown_dwarf_call_is_typed_on_a_faint_spectrum() -> None:
    # 31 of 616 empty sky positions were called a star or "not a brown dwarf" by the fit.
    for klass, verdict in (("star", "Looks like an ordinary star, not a brown dwarf."),
                           ("not a brown dwarf",
                            "Looks like a dusty or young red source, not a brown dwarf.")):
        fit = {**BD, "class": klass, "verdict": verdict, "detection_sigma": 30.0}
        match, notes = vet(fit, [FAINT], blended=False)
        assert match is None and len(notes) == 1
        assert "does not show a clear brown dwarf" in notes[0] and notes[0].endswith(verdict)


def test_stronger_reasons_come_first_and_the_fit_sentence_only_stands_alone() -> None:
    from pxs.typegate import UNSEEN_REASON

    count = faint_reason(FAINT)
    why = "The spectrum is not classified because a brighter catalogued source ..."
    for fit in ({**BD, "detection_sigma": 14.0},
                {**BD, "class": "uncertain", "detection_sigma": 14.0}):
        assert vet(fit, [FAINT], blended=False, seen=False) == (None, [UNSEEN_REASON, count])
        assert vet(fit, [FAINT], blended=True) == (None, [BLEND_REASON, count])
        assert vet(fit, [FAINT], blended=False, contaminated=why) == (None, [why, count])


def test_a_faint_type_needs_neighbour_checks_that_ran_and_found_nothing() -> None:
    from pxs.typegate import FAINT_NEIGHBOUR, FAINT_UNCHECKED

    fit = {**BD, "detection_sigma": 14.0}
    assert vet(fit, [FAINT], blended=False, checked=False) == (None, [FAINT_UNCHECKED])
    caution = "A catalogued source 4.9 arcsec away may contribute ...; treat the type as provisional."
    assert vet(fit, [FAINT], blended=False, caution=caution) == (None, [FAINT_NEIGHBOUR])
    for sentence in (FAINT_UNCHECKED, FAINT_NEIGHBOUR):
        assert "is not classified because" in sentence
    # A spectrum that passes the count is typed as before when the checks could not run.
    bright = [_spec(40, 6, 10.0)]
    assert vet(MATCH, bright, blended=False, checked=False) == (MATCH, [])


def test_neighbour_checks_count_as_run_only_with_both_lists_and_a_magnitude() -> None:
    from types import SimpleNamespace

    from pxs.typegate import neighbours_checked

    known = SimpleNamespace(w1_mag=17.3, w2_mag=None)
    assert neighbours_checked(known, [], gaia_failed=False)
    assert not neighbours_checked(known, None, gaia_failed=False)  # CatWISE did not answer
    assert not neighbours_checked(known, [], gaia_failed=True)
    assert not neighbours_checked(SimpleNamespace(w1_mag=None, w2_mag=None), [], gaia_failed=False)


def test_no_match_on_a_spectrum_with_too_few_usable_points_gives_a_reason() -> None:
    # RW Aurigae: saturated nearly everywhere, 5 usable points between 1.0 and 5.0 um.
    pts = [{"wl_um": 0.75 + 0.02 * i, "flux": 100.0, "err": 30.0, "flagged": False,
            "detector": 1} for i in range(11)]  # 0.75-0.95 um: outside the templates
    pts += [{"wl_um": w, "flux": 150.0, "err": 50.0, "flagged": False, "detector": 2}
            for w in (1.07, 1.09, 1.19, 2.41, 4.85)]
    pts += [{"wl_um": 3.0, "flux": None, "err": None, "flagged": True, "detector": 4}]
    match, notes = vet(None, [{"id": "spx-2025a", "points": []}, {"id": "spx-all", "points": pts}],
                       blended=False)
    assert match is None
    assert notes == [("The spectrum is not classified because only 5 of its points between 1.0 "
                      "and 5.0 µm are usable, and at least 8 are needed to compare it with the "
                      "templates.")]
