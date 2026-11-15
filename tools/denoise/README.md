# Learned residual model for the slow-mover search (experiment, 15 Nov 2026)

Question: can a learned model of SPHEREx image stamps make faint point sources easier to
detect or measure than the current shift-and-stack search, without inventing sources and
without biasing flux? Nothing here is wired into the pipeline or the site.

## What the model learns, and why

For point sources in Gaussian noise with a known PSF the matched filter and shift-and-stack
are already near optimal, so the model is not asked for a noise-free image. It predicts the
part of each difference image (search frame minus wavelength-matched reference from other
passes) that is predictable without looking at the pixel itself: the reference's own noise,
static-sky subtraction residuals and structure wider than a point source. That prediction is
subtracted before the matched filter; masks, trials and detection are unchanged.

Inputs (`features.py`): reference channels built only from passes at least 60 days away (the
matched reference, a deep all-wavelength reference, the wavelength offset of the match, the
reference noise), frame scalars (wavelength, detector, PSF peak and width), and the search
frame's own whitened difference image seen only outside a 5x5 px hole around the predicted
pixel (`model.py`, checked numerically by `blind_check`). A mover is absent from the
references and hidden by the hole, so by construction it cannot be predicted and subtracted,
apart from PSF wings beyond the hole (measured by gate 2).

Training (`train.py`) is self-supervised, Noise2Noise in spirit: the target is the search
frame's whitened difference image, the inputs are independent exposures of the same sky
(other passes, matched per pixel in wavelength as `pxs.movers.difference` does, each frame
zodi- and background-subtracted) plus the blind ring. Input and target noise are independent
(the hole is wider than the ~1 px correlation that resampling introduces), so the minimiser
is the predictable residual. The search frame's own variance is never an unblinded input,
because it carries the photon noise of sources.

## The gate (written before any gate result existed)

Fields: the 12 fields and passes of the validation campaign (`deploy/modal_movers.py`). None
is used for training, checkpoint choice or code tests; those use the T/D/V fields in
`modal_denoise.py`. Two arms on identical data: `base` = `pxs.movers.core.run_core`
unchanged; `den` = the same functions with the prediction subtracted from the difference
cube. Injections are the campaign's (same seeds: 6 runs x 25 sources per field, 20-400 uJy).

1. Completeness at fixed false-alarm rate. The false-alarm rate is the pooled count of
   mirrored-null detections. Baseline threshold 7.0 (as shipped) gives N0. The `den`
   threshold is the lowest value on a 0.05 grid in [5, 12] whose pooled `den` null count is
   <= N0. A source is recovered at a threshold when `pxs.movers.completeness.match` (run at
   S/N 5) matched it to a detection at or above the threshold. The 50% and 90% fluxes come
   from `completeness.curve` (12 bins) and `Curve.flux_at`. Uncertainty: 2000 bootstrap
   resamples of fields, and of sources within each field, the same resample for both arms,
   with N0 and the `den` threshold recomputed each time. Pass only if the 95% interval of
   flux(den)/flux(base) lies below 1 for both levels.
2. Flux fidelity. Forced flux summed along each injected track (all injected sources, found
   or not), both arms. Sources whose baseline forced flux is more than 5 sigma from the
   injected flux are dropped from both arms. In four log-flux bins and overall, the paired
   shift mean((F_den - F_base) / F_injected) must satisfy |shift| <= max(2 SE, 1%). The
   absolute bias of each arm is reported beside it (the baseline's own bias, for example
   from nearest-pixel rounding, is not the model's).
3. Nothing invented. Mirrored-null detections (no real mover stacks along mirrored tracks)
   pooled over the gate fields, same threshold in both arms: the `den` count must be <= the
   baseline count at S/N 7, and <= baseline + sqrt(baseline) at S/N 5. Real-sky peaks are
   reported too.

Pass = all three. `analyze.py` computes them and writes `result.json`.

### One change to the `den` arm, made on validation fields before the gate ran

The first smoke test (validation field V03, not a gate field) showed that subtracting the
prediction while keeping the pipeline's variance leaves the noise miscalibrated: the
variance still contains the matched reference's term, but the prediction has removed most
of that noise, by different amounts in different places. So the `den` arm also removes the
reference's variance term from the cube (`units.corrected_cube`). With that, the per-frame
noise scale of the matched filter on V03 is the same in both arms (0.904 and 0.903). The
three criteria above were not changed.

## What was run (Modal, 15 Nov 2026)

- Training cubes (`--stage build`, CPU): 32 fields (T01-T20 at high galactic latitude,
  D01-D12 at |b| of roughly 10-27 deg), up to three passes each, 5,104 search frames of
  195x195 px, 164 million valid pixel targets. One training pair is one search frame's
  difference image (target) with the references from the other passes and its own blind
  ring (input). Validation: V01-V04, 563 frames. None within a degree of a gate field.
- Training (`--stage train --tag v1`, one A10G): 289,425 parameters, 6,000 steps of 64
  crops of 96x96 px, 16 minutes; a 500-step test before it and one aborted start bring the
  total to about 0.35 GPU-hours. Checkpoint with the lowest validation loss (step 5,500).
  It removes 47% of the whitened difference-image variance on the validation fields and
  34-54% on the gate fields. Most of that is the matched reference's own noise: the
  reference at a pixel is the mean of only a few frames, so it carries about 30% of the
  difference image's variance, and the model predicts the static sky from all references.
- Gate (`--stage gate --tag v1`, CPU): 48 units, 1,800 injected sources. The baseline arm
  reproduces the campaign (50% and 90% fluxes 70.1 and 105.5 uJy; published 68.4 and 106.1
  from 8 runs; the same null counts at S/N 7 field by field).

## Result: the gate failed (`result.json`)

1. Completeness at matched false-alarm rate: passed. N0 = 62 null detections at S/N >= 7;
   the `den` threshold with no more than 62 is 6.90 (bootstrap 95%: 6.80-7.60).
   50% flux 70.1 -> 57.3 uJy, ratio 0.82 (95% interval 0.76-0.92).
   90% flux 105.5 -> 92.9 uJy, ratio 0.88 (0.59-0.97).
   At the same threshold 7.0: 1,020 -> 1,123 of 1,800 recovered (109 gained, 6 lost).
2. Flux fidelity: failed. Paired shift in the four flux bins: -8.4 +- 3.5%, -7.2 +- 2.3%,
   -13.6 +- 11.3%, -2.4 +- 0.5%; overall -9.0 +- 3.6%. Split into parts, the shift is a
   constant -2.69 +- 0.23 uJy with no proportional part (+0.03 +- 0.15%). So the model does
   not subtract source flux (the blind hole works), but every flux comes out 2.7 uJy low.
3. Nothing invented: passed by the rule, with caveats. Null detections 62 -> 60 at S/N 7
   and 712 -> 682 at S/N 5, but 128 -> 146 at S/N 6. At S/N 7 the count rose in three
   fields (B5 4 -> 6, B6 4 -> 5, Eris 2 -> 4) and fell in three (Barnard's Star 22 -> 18,
   WISE 0855 21 -> 19, Makemake 1 -> 0). The strongest null peak got stronger in 9 of 12
   fields (for example WISE 0855 18.4 -> 25.5): artefacts the model cannot predict keep
   their flux while the noise under them drops. Real-sky peaks at S/N 7: 60 -> 63.

A model that shifts fluxes fails whatever its completeness, so the verdict is fail.

## Why, and a follow-up that also failed (`selection.json`, `result_followup.json`)

The follow-up is not the gate and does not change the verdict. It was run to find out why
the flux moved.

The Level 2 variance of a pixel includes that pixel's own measured signal, so inverse-
variance weights are lower where the noise happens to be high. That biases weighted fluxes
low and, usefully, also suppresses positive artefacts. In the baseline the reference's
variance term dilutes the effect and the fluxes come out unbiased (constant term
+0.2 +- 0.4 uJy). Once the model has removed the reference noise, the weights follow the
search frame alone and the bias shows.

Check on the validation fields (`--stage select`, 200 sources, rule in
`select_variant.py`, fixed before any of these results was read): the same model with three
variance choices. Relative
to the gate's choice, a 7x7 median of the variance moves every flux by +3.05 +- 0.08 uJy;
the pipeline variance unchanged by +1.04 +- 0.05 uJy. Only the smoothed variance met the
flux rule, so it alone went to a test on 12 fields used for nothing before (F01-F12,
`--stage fresh --variant smoothed`, same three criteria, 1,800 sources):

- Flux: passed. Constant term -0.09 +- 0.22 uJy, proportional -0.09 +- 0.14%.
- Null peaks: failed. 36 -> 84 at S/N 7, 99 -> 227 at S/N 6, 668 -> 773 at S/N 5.
- Completeness at matched false-alarm rate: failed. The threshold has to rise to 9.15
  (7.55-9.95); 50% flux ratio 1.00 (0.89-1.10), 90% flux ratio 0.98 (0.81-1.15).

So the noise reduction is real (the S/N of injected sources rises by a median 23% on the
gate fields and 25% on the fresh ones), but with the
pipeline's present weighting it cannot be had with both unbiased fluxes and an unchanged
false-peak rate: per-pixel weights give the first gate and lose the second, smoothed
weights do the reverse. The false peaks are artefacts, not noise, and the model does not
remove them. What it would take: a variance model that does not follow each pixel's own
noise, plus explicit rejection of the artefacts those weights were hiding; then this gate
again on fields not used here.

## Files

`features.py` inputs and target; `model.py` network and blind-spot check; `train.py`
training; `units.py` container work for cubes, diagnostics and both arms; `modal_denoise.py`
the Modal app; `analyze.py` the three gates; `select_variant.py` the follow-up's selection
rule; `test_denoise.py` numpy-only checks (`uv run pytest tools/denoise -q`). Volume
`pxs-denoise`: `train/` cubes, `run/v1/` checkpoint and log, `gate/v1/` gate units,
`gate/v1-select/` and `gate/v1-fresh-smoothed/` follow-up units, `shares/v1/` validation
diagnostics. The 12 gate fields have now been looked at; a new variant needs new fields.
