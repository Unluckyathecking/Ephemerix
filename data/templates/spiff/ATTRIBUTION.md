# SPIFF hybrid templates

Standard spectral-type templates on the SPHEREx channel grid, vendored unchanged.

- Source: Gagné et al. 2026, "SPIFF" (arXiv:2604.22012), Zenodo record
  [10.5281/zenodo.19051216](https://doi.org/10.5281/zenodo.19051216), file
  `spiff_templates_hybrid_csv.zip` (`spiff_templates/hybrid_csv/<type>_spherex_standard.csv`).
- Download URL: https://zenodo.org/api/records/19051216/files/spiff_templates_hybrid_csv.zip/content
- Licence: CC-BY-4.0 (https://creativecommons.org/licenses/by/4.0/). Please cite Gagné et al. 2026.
- Fetched: 2026-11-14 (bundle version QR2-2026-04-24).
- Columns: `WAVELENGTH_MICRONS, FLUX_FLAMBDA, FLUX_FLAMBDA_UNC`. 90 channels, 1.0066 to 4.9673 um.
- All 47 files are kept: 24 field types (M8, M9, L0-L9, T0-T9, Y0, Y1) and 23 low-gravity or
  subdwarf variants. `pxs.typing` uses only the 24 field types.
- `esdL8` and `sdT4` each contain 2 NaN values (not used by `pxs.typing`).
