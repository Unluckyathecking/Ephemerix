# View manifest: the contract between pipeline and frontend

One JSON document, the **view manifest**, describes everything the page shows for one sky position. The pipeline writes it; the frontend only reads it. The same schema is served two ways:

- **Gallery (static):** `gallery/index.json` lists prebuilt targets; each lives at `gallery/<slug>/manifest.json` with its images beside it. This is what the judged demo uses, so it must work with no backend.
- **Live:** `GET /api/view?ra=&dec=&pmra=&pmdec=&epoch=&fov=` returns the same manifest, built on demand. It may take tens of seconds.

Image URLs in a manifest are relative to the manifest's own URL.

## Conventions
- Angles in degrees (ICRS) unless a field name says `_arcsec` or `_masyr`. Dates are ISO 8601 UTC; `mjd` is given as well.
- Proper motion is `pmra_masyr` (already multiplied by cos dec) and `pmdec_masyr`, with the `epoch` (decimal year) the position refers to.
- **Every image in a manifest is on one common grid:** north up, east left, `size_px` square, centred on the query position `center`, at `fov_arcsec / size_px` arcsec per pixel. The grid is fixed on the sky. It does not follow the target, so a moving object moves across the frames.
- Pixel coordinates are `[x, y]` with the origin at the top-left of the image, x to the right, y down, in units of image pixels (floats). They use pixel edges: the top-left corner of the image is `[0, 0]`, the grid centre is `[size_px/2, size_px/2]`, and pixel `i` covers `[i, i+1)`.
- Images are 8-bit greyscale PNG, rendered by the pipeline with one fixed stretch per `(mission, band)` so brightness is comparable from epoch to epoch.

## Manifest

```jsonc
{
  "schema": 1,
  "generated": "2026-11-14T15:00:00Z",
  "target": {
    "name": "WISE 0855-0714",        // or null for a bare position
    "slug": "wise-0855",             // gallery only
    "ra": 133.7835555, "dec": -7.2440520, "epoch": 2015.405,
    "pmra_masyr": -8123.7, "pmdec_masyr": 673.2,   // null when unknown
    "blurb": "The coldest known brown dwarf, 7.4 light-years away." // gallery only
  },
  "center": { "ra": 133.7765, "dec": -7.2434 },   // centre of the image grid
  "fov_arcsec": 240,
  "size_px": 240,

  "frames": [                         // sorted by date
    {
      "id": "wise-w2-2010a",
      "mission": "WISE",              // "WISE" | "SPHEREx"
      "band": "W2",                   // frame-set id, unique and URL-safe: "W1", "W2", "spx-b1" ... "spx-b6"
      "wavelength_um": [4.0, 5.2],    // passband or stacking window
      "date": "2010-05-08T00:00:00Z", "mjd": 55324.0,
      "date_span_days": 1.2,          // spread of the exposures in the stack
      "n_exposures": 14,
      "native_pixscale_arcsec": 2.75,
      "image": "frames/wise-w2-2010a.png",
      "predicted_px": [150.2, 119.6], // where pm puts the target at this date; null if pm unknown
      "centroid_px": [149.8, 120.1],  // measured, or null if not detected
      "centroid_err_arcsec": 0.4,     // null with centroid_px
      "flag_fraction": 0.0,           // share of stacked pixels dropped by quality flags
      "no_data_fraction": 0.0,        // (new) share of the frame with no usable measurement: no coverage, or flagged in most exposures (gaps closed over 2 px)
      "no_data_near_target": 0.0,     // (new) that share within 30" of the target's position; null when the position is off the frame
      "gaps_image": null,             // (new) "frames/<id>-gaps.png": 255 where there is no data, 0 elsewhere, same size as `image`; null when there are no gaps
      "warnings": []                  // e.g. ["saturated"]
    }
  ],

  "track": [                          // predicted path for drawing, one point per year; [] if pm unknown
    { "year": 2010.0, "px": [152.0, 119.5] }
  ],

  "spectra": [                        // one per SPHEREx epoch, plus "all" when epochs are combined
    {
      "id": "spx-2025b",
      "label": "Nov 2025",
      "date_start": "2025-11-02T00:00:00Z", "date_end": "2025-11-16T00:00:00Z",
      "unit": "mJy",                  // F_nu
      "points": [
        { "wl_um": 4.52, "bw_um": 0.04, "flux": 0.31, "err": 0.05, "detector": 6, "flagged": false }
      ]
    }
  ],

  "match": {                          // null when fewer than 8 usable points
    "spectrum_id": "spx-all",
    "best": { "type": "T8", "chi2": 160.2, "dof": 78 },     // lowest score of all candidates; dof = points used - free parameters
    "runner_up": { "type": "T9", "chi2": 210.0, "dof": 78 },
    "delta_chi2": 22.1,               // runner-up score minus best score (see "score" below; was a raw chi2 difference)
    "verdict": "Consistent with a cold brown dwarf, type T7 to T9 (best match T8).",   // one plain sentence
    "confidence": "high",             // "high" | "medium" | "low"; refers to the class call only
    "class": "brown dwarf",           // "brown dwarf" | "star" | "not a brown dwarf" (new) | "uncertain"
    "type_range": ["T7", "T9"],       // two real template names, at least one subtype either side of the best; null when class is "star" or "not a brown dwarf"
    "range_open_warm": false,         // new: true when the range reaches M8, i.e. "M8 or warmer"
    "range_open_cold": false,         // new: true when the range reaches Y1, i.e. "Y1 or colder"
    "delta_class": 1016.0,            // score of the best model of the losing side minus the winning side's (>= 0)
    "detection_sigma": 69.4,          // new: significance of the best model against no source at all, over every point used (see Notes)
    "pair": null,                     // new; or { "types": ["T1", "T6"], "chi2": 88.9, "delta_vs_single": 44.7, "model": "T1 + T6" }
    "bands_detected": ["H2O 1.4 um", "CH4 3.3 um"],         // new: molecular bands of the best template seen in the data
    "candidates": [                   // the 24 templates and the best of each comparison family, sorted by score
      { "type": "T8", "family": "brown dwarf", "chi2": 160.2, "score": 169.0 },
      { "type": "dust + star (dust 400 K; star 10000 K)", "family": "star + dust", "chi2": 1100.0, "score": 1185.0 }
    ],
    "models": {                       // best and runner-up scaled to the data, same unit as the spectrum
      "T8": [ [1.01, 0.002], [1.05, 0.003] ]   // plus the pair's summed curve under pair.model ("T1 + T6") when pair is set (new)
    },
    "per_pass": [                     // new, optional: each SPHEREx pass typed on its own; absent with one pass
      { "id": "spx-2025a", "label": "Apr 2025", "typed": true, "class": "brown dwarf", "type": "T8",
        "type_range": ["T7", "T9"], "reason": "" }   // typed false: class/type/type_range null, reason says why
    ],
    "pass_agreement": { "status": "agree", "sentence": "All 2 passes typed on their own agree." },  // new, with per_pass; status "agree" | "disagree" | "too few"
    "provisional": "A catalogued source (W2 16.7) 4.9 arcsec away may contribute about 15% of the light at these wavelengths, or more; treat the type as provisional.",  // new, optional: present when a neighbour is estimated at 10-25% of the target's light (25% or more refuses the type, match null); show the type as provisional with this sentence, which is also in warnings. Also present, with a different sentence, for a type given to a faint object (see Notes)
    "provisional_kind": "neighbour",  // new, with provisional: "neighbour" (the case above) or "faint" (a type from a fit to all points of an object too faint to detect at many wavelengths one by one); absent in manifests built before 15 Nov 2026, where it means "neighbour"
    "method": "Chi-square fits of the SPIFF brown-dwarf templates (Gagné et al., arXiv:2604.22012) and of non-brown-dwarf comparisons ..."
  },

  "features": [                       // molecular bands to shade on the spectrum plot
    { "label": "CH4", "wl_um": [3.1, 3.6] }
  ],

  "overlays": {                       // catalogue sources inside the field, positions at catalogue epoch
    "gaia": [ { "id": "4472832130942575872", "ra": 0, "dec": 0, "epoch": 2016.0,
                "pmra_masyr": 0, "pmdec_masyr": 0, "g_mag": 8.2,
                "parallax_mas": 546.98, "parallax_error_mas": 0.04 } ],   // parallax fields new, null when Gaia has none
    "catwise": [ { "id": "J085506.91-071437.5", "ra": 0, "dec": 0, "epoch": 2015.405,
                   "pmra_masyr": 0, "pmdec_masyr": 0, "w1_mag": 19.5, "w2_mag": 15.5 } ]
  },

  "vetting": {                        // optional; any field may be null
    "w1_mag": 19.5, "w2_mag": 13.8, "w1_w2": 5.7,
    "reduced_pm_w2": 23.4,            // H_W2 = W2 + 5 log10(mu in arcsec/yr) + 5
    "catalogue": "CatWISE2020 J085506.91-071437.5"
  },

  "measured_motion": {                // from the centroids; null if not measured
    "pmra_masyr": -8100, "pmdec_masyr": 650, "err_masyr": 120,
    "baseline_years": 15.9, "n_detections": 21,
    // Only when fewer than 2 detections could be used and the motion was instead fitted on
    // all W2 images at once (no image shows the target on its own): "method": "all_frames",
    // "n_frames": 23 and "n_detections": 0. `warnings` then carries a sentence saying so.
    "parallax_model": "fixed",        // "fixed" (known parallax held fixed), "fitted" (10+ epochs, value not reported) or "none"
    "parallax_mas": 439.0             // the fixed value, else null: the target's own, or its Gaia parallax when > 0 at 5 sigma or more (new)
  },

  "motion_not_measured": null,        // (new) a motion was fitted but is too thin to mean anything: {"reason", "n_detections", "baseline_years"}; measured_motion is then null
  "field": {                          // (new) hard fields, see Notes
    "saturated": false, "saturated_missions": [],            // "SPHEREx", "WISE": glare covers the target
    "no_data_near_target": { "SPHEREx": 0.0, "WISE": 0.02 }, // median frame per mission
    "crowded": false,                 // null when CatWISE did not answer
    "crowding": { "crowded": false, "catwise_sources": 124, "faintest_w2": 17.85 } // null with crowded null
  },

  "warnings": [],                     // plain sentences for the user, e.g. data gaps; field and motion sentences come first
  "field_movers": { "status": "searched", "movers": [], "sentence": "..." },  // optional, new: what else moved in the field; see "Field movers block"

  "warnings": [],                     // plain sentences for the user, e.g. data gaps
  "degraded": false,                  // true when a mission source or catalogue fetch failed; such views are not cached for long
  "credits": [ "SPHEREx QR2/QR3 via NASA/IPAC IRSA (10.26131/IRSA652)" ]
}
```

## Field movers block (optional)

`field_movers` is one extra top-level key written by `pxs.build` for every view, gallery or live (`src/pxs/fieldmovers/`). It is additive: `schema` stays 1, readers that do not know the key ignore it, and manifests built before it have none. It answers "what else in this patch moved between 2010 and 2024?" without using the target's position: every source of every WISE visit (W2 and W1, S/N 4 or more in a single visit) is linked into a track, each track gets a straight-line motion with an error, and a track is a mover when its motion is at least `limits.significance_min` times its error, it shifted at least `limits.shift_min_arcsec` over the baseline and it was seen in at least 70% of the visits it could be. A mover seen in both bands must move the same way in both. `sentence` is the line to show; the rest is for drawing.

```jsonc
"field_movers": {
  "status": "searched",               // or "not_searched": then only reason, method, movers (empty) and sentence are present
  "reason": null,                     // why it was not searched: fewer than 6 WISE visits, a catalogue query failed, or the search failed
  "method": "wise_visit_tracks",
  "bands": ["W2", "W1"],
  "first_year": 2010.3, "last_year": 2024.3, "baseline_years": 14.0,
  "n_epochs": { "W2": 23, "W1": 23 },  // visits searched per band
  "n_tracked": { "W2": 15, "W1": 27 }, // sources followed through 6 or more visits
  "limits": { "snr_min": 4.0, "significance_min": 6.0, "shift_min_arcsec": 1.0, "min_epochs": 6 },
  "movers": [ {                       // most significant first
    "label": "target",                // "target" | "gaia" | "catwise" | "candidate"
    "gaia_id": null,                  // the Gaia DR3 star whose proper motion matches (label "gaia")
    "catwise_id": "J085510.74-071442.5", // CatWISE2020 source on the track: its motion matches when label is "catwise"; otherwise just the catalogued source nearest the path, or null
    "bands": ["W2"],                  // measured in the first; the others saw the same motion
    "epoch": 2018.13,                 // decimal year of px, ra, dec
    "px": [126.9, 118.9], "ra": 133.78, "dec": -7.24,   // same pixel convention as frames
    "first_px": [61.2, 124.2], "last_px": [175.1, 114.9], // fitted place at first_year and last_year, clipped to the image
    "first_year": 2010.34, "last_year": 2024.33,          // of the visits it was seen in
    "pmra_masyr": -8131.1, "pmdec_masyr": 663.5, "err_masyr": 25.3,  // 1 sigma per axis
    "motion_arcsec_yr": 8.158, "shift_arcsec": 114.2,
    "significance": 322.2,            // motion / error
    "snr": 21.0,                      // median single-visit S/N
    "n_epochs": 21,
    "epochs": ["wise-w2-2010a", "wise-w2-2010b"]          // ids of the frames it was seen in
  } ],
  "n_known": 0,                       // movers explained by Gaia or CatWISE
  "n_candidates": 0,                  // movers no catalogue explains: counted here, listed in movers only when candidates_withheld is false
  "candidates_withheld": true,        // the shipped setting (fieldmovers.block.SHIP_CANDIDATES): known movers only
  "n_contradicted": 0,                // "movers" at a Gaia star whose Gaia motion disagrees: false alarms, counted, never listed
  "n_band_conflicts": 0,              // movers dropped because W2 and W1 disagree
  "null_count": 0.0, "null_max": 0, "null_trials": 10,   // movers found by the same search with the visit dates shuffled: mean and largest over the trials
  "sentence": "We searched this patch for anything else that moved between 2010 and 2024. We found nothing unexplained. The search also picked up the target itself without being told where it is."
}
```

Labels. `target`: the track passes through the target's place. `gaia`: a Gaia DR3 star with a proper motion is within 3" of the track and the two motions agree in size and direction (their difference is within 3 sigma or 30% of the measured motion). `catwise`: the same test against a CatWISE2020 source on the track's 2010-2019 path; CatWISE is made from the same images, so this means "already catalogued as moving", not independently confirmed. `candidate`: none of these. A candidate is an unexplained candidate, never a discovery: judge it against `null_count` for the same field, and expect none in most fields. As shipped, candidates are counted (`n_candidates`) but not listed, and `sentence` says so when there are any: in the 17 gallery fields the search turned up none, so its false-alarm rate (0.007 a field with the dates shuffled) could not be shown to be below the rate of real ones. What the search cannot see: a source too faint to show in most single visits (planted movers of S/N 5 per visit, about W2 14.7, are recovered about half the time; S/N 8 and up, three in four), anything that shifts less than 1" in 14 years, and a source in the wings of one 40 times brighter. The numbers behind the limits are in `src/pxs/fieldmovers/__init__.py` and come from `probes/astro/field_movers.py`.

## Solar System body block (optional)

A manifest written by `python -m pxs.solarsystem` (`src/pxs/solarsystem/`) for a known Solar System body (Haumea, Makemake, ...) is an ordinary schema-1 manifest plus one extra top-level key, `solar_system`. It is additive: `schema` stays 1, readers that do not know the key ignore it, and its absence means an ordinary sky-position view. In such a manifest the schema-1 part is filled as follows: `frames` are short sky-fixed sub-stacks of the one pass named by `shown_pass`, in that pass's best detector band, and the body steps across them; `predicted_px` is the body's JPL Horizons position on each; `track` is those positions with decimal years; `spectra` are one per analysed pass (control subtracted, mJy); `match` is null (brown-dwarf templates do not apply) with the reason in `warnings`; `features` are the ice-band windows below; `overlays` is empty and `vetting` and `measured_motion` are null.

```jsonc
"solar_system": {
  "designation": "136108", "type": "dwarf planet", "horizons_command": "136108;",
  "composition": "crystalline water ice ...",         // published composition, a sentence
  "composition_ref": "Dumas et al. 2011 ...",
  "shown_pass": "spx-2025a",                          // the pass the sky-fixed frames come from; null if none detected
  "passes": [ {                                       // every analysed pass, by date
    "id": "spx-2025a",                                // same id as its entry in spectra
    "date_start": "...", "date_end": "...",
    "n_frames": 116, "n_measured": 110,               // exposures containing the body; exposures measured
    "bands": [ { "band": "spx-b1", "wavelength_um": [0.75, 1.10], "n": 17,
                 "flux_ujy": 572.56, "err_ujy": 11.82, "snr": 48.44 } ],   // body minus control, microjansky
    "bands_before_control": [ ... ],                  // same shape, before the control subtraction
    "control": { "n_positions": 8, "n_frames": 140, "bands": [ ... ] },    // null when run with --no-control
    "best_band": "spx-b1", "best_snr": 48.44,
    "detected": true,                                 // S/N >= 5 in two bands (>= 50 if saturation leaves one band); see outcome
    "outcome": "detected",                            // added Nov 2026: "detected", "marginal" or "not detected";
                                                      // "marginal": S/N >= 5 in one band only, which empty control
                                                      // tracks give in about 6% of passes;
                                                      // before Nov 2026 "detected" meant best band S/N >= 5
    "ephemeris": [ { "mjd": 0, "ra": 0, "dec": 0, "rate_arcsec_h": 0, "vmag": 0,
                     "r_au": 50.3, "delta_au": 50.1, "phase_deg": 1.1, "elong_deg": 95.0 } ]  // one per day measured
  } ],
  "skipped_passes": [ { "date_start": "...", "n_candidate_frames": 4,
                        "reason": "fewer than 6 exposures contain the body" } ],
  "reflectance": [ {                                  // one per detected pass, plus "all-detected" when there are 2+
    "spectrum_id": "spx-2025a",                       // a spectra[].id, or "all-detected"
    "norm_window_um": [0.75, 1.30],                   // reflectance is 1 on average here
    "thermal_cutoff_um": null,                        // points at or beyond this were dropped (thermal emission); null: none
    "r_au": 50.3,
    "points": [ { "wl_um": 0.753, "bw_um": 0.018, "refl": 0.98, "err": 0.07 } ],  // dimensionless, sorted by wavelength
    "band_depths": [ {
      "label": "3.0 um (H2O)", "wl_um": [2.90, 3.15], "n_band": 3, "n_continuum": 25,
      "ratio": -0.040, "err": 0.054,                  // mean in-band / mean continuum reflectance, 1 sigma; may be < 0 from noise
      "depth": null,                                  // 1 - ratio; null when saturated
      "saturated": true, "depth_min": 0.911,          // see below; depth_min is null when not saturated
      "sigma": 19.3, "detected": true                 // (1 - ratio) / err; detected at sigma >= 3
    } ],
    "reading": "SPHEREx sees absorption at ..."       // authored sentences built from the depths
  } ],
  "body_frames": {                                    // body-centred images: the body stays at the centre, stars trail
    "note": "...", "size_px": 90,
    "frames": [ { "id": "spx-2025a-spx-b1-body", "band": "spx-b1", "wavelength_um": [0.75, 1.10],
                  "date": "...", "mjd": 0, "date_span_days": 6.1, "n_exposures": 17,
                  "image": "body/spx-2025a-spx-b1-body.png" } ]   // id starts with its pass id; one per band per detected pass
  },
  "sky_track_arcsec": 91.4,                           // how far the body moved across the shown frames
  "detector_bands": { "spx-b1": [0.75, 1.10], ... },
  "frame_search": { "index_days": 168, "sia_cones": 35, "failed_sia_cones": 0, "candidate_frames": 368 },  // null without an ephemeris
  "timings_s": { "photometry": 4.7, ... },            // wall seconds per stage
  "method": "Forced ePSF photometry at the JPL Horizons position ..."
}
```

- Units: `bands[].flux_ujy` and `err_ujy` are microjansky; `spectra[].points` are mJy, as everywhere else; reflectance and depths are dimensionless.
- Band depth: 1 - (inverse-variance mean reflectance in the window / that over 0.75-1.30 µm). One shared continuum ignores any slope, and at R about 40 the water- and methane-ice bands overlap; see `bands.py`.
- Saturated bands (new): where the ice absorbs nearly all light the in-band flux is zero within its noise, so `ratio` can fall below 0 and `1 - ratio` above 1. When `ratio < 2 err` the band is `saturated`, `depth` is null and `depth_min = 1 - (max(ratio, 0) + 1.645 err)` is a one-sided 95% lower limit (the ratio is clamped at 0 first, so a downward fluctuation gives no extra depth). Show it as "deeper than X%"; never print `1 - ratio` for such a band.

## Gallery index

```jsonc
{ "schema": 1,
  "targets": [ { "slug": "wise-0855", "name": "WISE 0855-0714", "blurb": "...",
                 "manifest": "wise-0855/manifest.json", "thumb": "wise-0855/thumb.png",
                 "ra": 133.7836, "dec": -7.2441,      // so a searched position can be matched to a gallery target
                 "known_type": "Y4", "tool_type": "Y1",
                 "group": "brief" } ] }   // new: heading the target is listed under (from data/targets.json); null when none
```

## Page URL (frontend state)
Everything a view needs is in the query string, so a link reproduces the view and can be embedded:

`?target=<slug>` for a gallery target, `?body=<name or designation>` for a Solar System body built live (new; for example `?body=136199` or `?body=C%2F2025%20N1`), or `?ra=&dec=` with optional `&pmra=&pmdec=&epoch=&fov=`. View state rides along: `&frame=<id>` (current frame), `&bands=W2,spx-4.6` (which frame sets are in the blink), `&spec=<id>`, `&zoom=<1 to 8>` (any decimal; whole numbers from older links work), `&follow=1|0` (follow the object, or keep the sky fixed), `&fc=1` (false-colour composite of three SPHEREx bands in the band strip), `&embed=1` (hide the chrome).

`mode=simple` or `mode=full` chooses between the simple view (the blink and a plain answer) and the full analysis. With no `mode`, a link that carries only a target, body or position opens the simple view, and a link that carries view state (`frame`, `bands`, `cmp`, `embed` and the like) opens the full one. The sky map is `explore.html`, with optional `?target=<slug>` or `?ra=&dec=&zoom=` (zoom 1 is the whole sky).

## Notes
- SPHEREx frame sets are the six detector bands: `spx-b1` 0.75-1.10, `spx-b2` 1.10-1.65, `spx-b3` 1.65-2.42, `spx-b4` 2.42-3.82, `spx-b5` 3.82-4.42, `spx-b6` 4.42-5.00 µm. The page labels sets from `mission` and `wavelength_um`, never from the id.
- `match` is null when the spectrum is too faint or too contaminated to classify, or has fewer than 8 usable points between 1.0 and 5.0 µm; the reason is an authored sentence in `warnings`. When several reasons apply, the stronger ones come first (target not found in any image, a Gaia star within one pixel, a brighter catalogued neighbour) and the faintness sentence last.
- `detection_sigma`: sqrt(chi2 of zero flux minus the smallest chi2 of any model), on the points the fit used. For a model with one free scale it is the matched-filter signal-to-noise of that model's amplitude, so it adds up points that are not detected one by one.
- Faint objects (`provisional_kind` "faint"). A spectrum with fewer than 15 points at S/N 3, or fewer than two detector arrays detecting it, is still typed when all of these hold: `detection_sigma` is at least 10; `class` is "brown dwarf" (a star or "not a brown dwarf" call on such a spectrum is not shown); the Gaia and CatWISE neighbour checks ran, with a W1 or W2 magnitude for the target, and found no neighbour adding 10% or more; and the target was found in at least one image. Its `type_range` is at least two subtypes either side of the best template instead of one. The 10 and the two subtypes were chosen from tests on fainter copies of the eight brighter gallery targets (`src/pxs/typegate.py`); neither is derived from first principles.
- Every string in `warnings` is a sentence written in the pipeline's code. Exception text never reaches a manifest.
- `bands` in the page URL lists `frame.band` ids. A frame set is all frames sharing one `band`.
- `features` may be empty. `match.models` curves are sampled on the template's own wavelength grid, not at the data wavelengths.
- Candidate families (`candidates[].family`): "brown dwarf" (the 24 SPIFF field templates M8-Y1, 2 free parameters: type and scale); "star" (blackbody 2500-10000 K with reddening A_V 0-20, 3 parameters), labelled `star (...)`; "dust" (the same below 2500 K), labelled `dust (...)`; "power law" (F_nu ~ lambda^alpha, alpha -2 to 4, 2 parameters); "star + dust" (a reddened star plus a 300-1500 K blackbody, 5 parameters), labelled `dust + star (...)`. The temperature and A_V in a label are the best grid point, not measurements: temperature and reddening are nearly degenerate at this resolution. `score` = chi2 / s2 + k ln n (BIC), with k the parameters, n the points used and s2 = max(1, smallest reduced chi2 of any candidate), so error bars that are uniformly too small do not decide the call. Only labels of the "star" family begin with "star"; read `class`, not the label, to know whether the source is a brown dwarf.
- `class`: "brown dwarf" needs the best template (L0 or later) to beat every comparison by a score margin of 10 (30 when the fit is poor, see below) and at least one molecular band of that template to be detected; "star" means a star, reddened or not, fits clearly better; "not a brown dwarf" (new) means a dusty, young or otherwise red featureless source fits clearly better; "uncertain" covers too few points, nothing fitting (best reduced chi2 above 10 after allowing for white noise larger than the errors), a tie, no band seen, a best match of M8 or M9 (the templates start at M8, so an ordinary late-M star cannot be excluded), and a red comparison winning when the source could be a brown dwarf colder than Y1.
- `match.confidence` refers to the class call only: "low" whenever `class` is "uncertain"; "medium" for a call made despite a poor fit (best reduced chi2 3-10) or by a score margin under 30; otherwise "high". `type_range` carries the subtype uncertainty.
- `type_range`: templates within delta chi2 4 x max(1, best template's reduced chi2) of the best, as one contiguous span, then widened to at least one subtype either side. The two names are always real templates; an open end is flagged by `range_open_warm` / `range_open_cold` and the verdict says "or warmer" / "or colder".
- `pair` is set only when `class` is "brown dwarf" and two templates at least 3 subtypes apart fit better than one template with a free colour tilt by at least 25 in rescaled chi2, the fainter one supplying at least 20% of the flux somewhere. `delta_vs_single` is that improvement. The verdict then names the pair.
- `thumb` is a square PNG of the band in which the target is best detected.
- Gaps in the images (new). A pixel flagged in most exposures (a saturated or bad pixel) holds a fill or the values of the few exposures that were not flagged, so it is not drawn through the stretch: a saturated core is white, and any other gap is drawn as one even patch at the median level of the data around it. `gaps_image` marks every such pixel, and every pixel with no coverage, so the page can show where they are. Display only: photometry and centroids are unchanged.
- `field` (new, `src/pxs/fieldcheck.py`). `saturated`: in the median WISE frame, at least 80% of the 30" disc around the target has no data, so glare covers it and not just a saturated core (median WISE shares: Betelgeuse 1.0, Sagittarius A* 1.0, R Draconis 0.48, Barnard's Star 0.12). `saturated_missions` then names WISE, and SPHEREx when at least half of its median disc has no data. A star that saturates only SPHEREx is not flagged. A view with no WISE frame at all (the WISE images could not be loaded) is judged from SPHEREx alone: `saturated` is true, with `saturated_missions` ["SPHEREx"] and a sentence naming SPHEREx only, when the median share is at least half in more than half of the SPHEREx bands shown. `crowded`: the CatWISE list (the 200 brightest around the field) is full, 100 or more inside the field, and its faintest source is brighter than W2 15; every gallery field reaches W2 16.3 or fainter. When either is true, one plain sentence for it opens `warnings`, glare first.
- Motion gate (new). Detections in frames with `flag_fraction` 0.5 or more are left out of the fit. A fitted motion from fewer than 4 detections (`n_frames` for "all_frames"), or over less than 3 years, is not published: `measured_motion` is null, `motion_not_measured` says why, and a sentence starting "Motion not measured:" follows the field sentences in `warnings`. An "all_frames" fit is also refused in glare. When the WISE search or stacking failed and the view has no WISE frame, a missing motion, or one over less than 3 years, is put down to that: `motion_not_measured.reason` is "the WISE images could not be loaded; a motion needs their years of positions", with the fit's `n_detections` and `baseline_years` (0 when there was none). The 16 measured gallery motions have at least 5 detections over 9.99 years or more and are unchanged (`tests/test_fieldcheck.py` replays them).
- The live API must send CORS headers when it is served from a different origin than the site, and that origin must be added to the site's Content-Security-Policy.
- The live API answers `202` with a job to poll for stage and progress; see `src/pxs/api/`.
- Solar System bodies (new): `GET /api/body/resolve?name=` only looks the name up (curated list, then the JPL Small-Body Database) and answers `{resolved, designation, name, kind}` or `{resolved: false, message, did_you_mean: [{designation, name}]}` (look up `designation`; SBDB refuses its own display names); it never starts a build. `GET /api/body?name=` answers like `/api/view` (200 with the cached manifest, else 202 with a job), 404 `{error, did_you_mean}` when no single body matches and 503 when SBDB does not answer. `name` is 1-40 characters of letters, digits, spaces and `/ ' ( ) . _ -`. Lookups share the `/api/resolve` rate limit and builds the `/api/view` one. The view is keyed by the body's Horizons command, the SPHEREx frame index and the UTC day, so it is rebuilt at most once a day. A build that runs short of time keeps the passes it measured, warns, and is `degraded`.
- Archive uptime (new): `GET /api/archives` is served from saved checks, not by the lookup service. A scheduled job (`archive_watch` in `deploy/modal_app.py`, `src/pxs/api/archivestatus.py`) checks every archive every 5 minutes with one light request each (a `TOP 1` query on the TAP schema for IRSA TAP, ESA Gaia and Data Lab; a one-row SIA query for IRSA images; a HEAD on each AWS bucket; Sesame for "Vega"; Horizons with no ephemeris; the Small-Body Database for asteroid 1), all at once, with no retry, and keeps 30 days of them. A check is "up", "slow" (answered after more than 5 s) or "down" (an HTTP error, a TAP error answer, or nothing within 5 s to connect and 10 s to answer, with a short `detail` such as "HTTP 502"). The default answer is `{checked_at, archives: [{id, name, used_for, backup, status, latency_ms, detail}], history: {<id>: {checks, answered, since, failed_last_hour}}, checks: {times, archives: {<id>: {codes, ms, fail}}}, days: {dates, archives: {<id>: [[checks, answered, slow], ...]}}}`: the newest check (`checked_at`, null when there is none), counts over the days held, every check of the last 24 hours (`codes`: one letter per time, "u", "s", "d" or "-" for not checked) and per-day sums for the last 30 UTC days. `?day=YYYY-MM-DD` answers `{day, checks}` for that day (400 for anything else, including a day more than 31 days back or after tomorrow in UTC; 404 for a day with no checks). Answers are public and cacheable: 5 minutes, or 30 days for a finished day. The read and storage are in `src/pxs/archivehistory.py`; the site serves the path through `web/api/archives.js`, not `web/middleware.js`.

## Changes
The schema is versioned with `schema`. Any change to it is made here first.
- 2026-11-15 (additive, no new field): `field.saturated_missions` may be ["SPHEREx"] alone and `motion_not_measured` may be set with no fitted motion, both only in a view whose WISE images could not be loaded (Notes: `field`, Motion gate). When IRSA's frame search does not answer, WISE frames are found from the public bucket instead (`src/pxs/wise/bucketsearch.py`); the manifest is the same shape, with frame times 3 to 5 s later (the frame header's time).
- 2026-11-15 (additive): `frames[].no_data_fraction`, `frames[].no_data_near_target`, `frames[].gaps_image`, top-level `field` and `motion_not_measured`; thin motions are no longer published in `measured_motion`.
