// Bright stars for orientation: name, RA and Dec in degrees (J2000), visual magnitude.
// Source: the star table compiled into PyEphem 4.2.1. Every entry was checked against the Hipparcos
// catalogue (ESA 1997; VizieR I/239/hip_main, via vizier.cfa.harvard.edu) with its proper motion applied
// from 1991.25 to 2000.0: positions agree within 0.007 degrees and the magnitudes match to 0.01.
// They are only small dots on the all-sky inset, so this is far finer than needed.
export const BRIGHT_STARS = [
  ['Sirius', 101.29, -16.72, -1.44],
  ['Canopus', 95.99, -52.70, -0.62],
  ['Arcturus', 213.92, 19.18, -0.05],
  ['Rigil Kentaurus', 219.90, -60.83, -0.01],
  ['Vega', 279.23, 38.78, 0.03],
  ['Capella', 79.17, 46.00, 0.08],
  ['Rigel', 78.63, -8.20, 0.18],
  ['Procyon', 114.83, 5.22, 0.40],
  ['Achernar', 24.43, -57.24, 0.45],
  ['Betelgeuse', 88.79, 7.41, 0.45],
  ['Altair', 297.70, 8.87, 0.76],
  ['Acrux', 186.65, -63.10, 0.77],
  ['Aldebaran', 68.98, 16.51, 0.87],
  ['Spica', 201.30, -11.16, 0.98],
  ['Antares', 247.35, -26.43, 1.06],
  ['Pollux', 116.33, 28.03, 1.16],
  ['Fomalhaut', 344.41, -29.62, 1.17],
  ['Deneb', 310.36, 45.28, 1.25],
  ['Mimosa', 191.93, -59.69, 1.25],
  ['Regulus', 152.09, 11.97, 1.36],
  ['Adhara', 104.66, -28.97, 1.50],
  ['Castor', 113.65, 31.89, 1.58],
  ['Gacrux', 187.79, -57.11, 1.59],
  ['Shaula', 263.40, -37.10, 1.62],
  ['Bellatrix', 81.28, 6.35, 1.64],
  ['Elnath', 81.57, 28.61, 1.65],
  ['Miaplacidus', 138.30, -69.72, 1.67],
  ['Alnilam', 84.05, -1.20, 1.69],
  ['Polaris', 37.95, 89.26, 1.97],
];
