# Technical Documentation — Sentinel-2 Change Analysis

Detailed reference for the change-analysis pipeline over an open-pit mining site
in Zambia, comparing two Sentinel-2 acquisitions (**2023-08-12** → **2023-09-02**).

For a quick start see [README.md](README.md); for the scientific write-up see
[report.md](report.md). This document is the engineering reference: architecture,
module-by-module API, algorithms with their maths, data and output specs,
configuration, design decisions, and troubleshooting.

---

## Table of contents
1. [Overview](#1-overview)
2. [Architecture & data flow](#2-architecture--data-flow)
3. [Repository layout](#3-repository-layout)
4. [Installation](#4-installation)
5. [Running the pipeline](#5-running-the-pipeline)
6. [Configuration reference](#6-configuration-reference)
7. [Input data specification](#7-input-data-specification)
8. [Module reference](#8-module-reference)
9. [Algorithms in depth](#9-algorithms-in-depth)
10. [Output specification](#10-output-specification)
11. [Database schema & queries](#11-database-schema--queries)
12. [The diagonal artifact](#12-the-diagonal-artifact)
13. [Results summary](#13-results-summary)
14. [Design decisions & trade-offs](#14-design-decisions--trade-offs)
15. [Extending the pipeline](#15-extending-the-pipeline)
16. [Troubleshooting](#16-troubleshooting)
17. [Limitations & future work](#17-limitations--future-work)

---

## 1. Overview

The pipeline ingests two co-registered, 3-band (Blue/Green/Red) Sentinel-2
scenes, detects spectral change between them, vectorises the change into
polygons with attributes, stores them in a spatial database, and produces both
static and interactive visualisations plus an interpretive report.

It maps to the five assignment parts:

| Part | Stage | Module |
|------|-------|--------|
| 1 | Data preparation | [`data_preparation.py`](src/data_preparation.py) |
| 2 | Change detection | [`change_detection.py`](src/change_detection.py) |
| 3 | Feature extraction & storage | [`feature_extraction.py`](src/feature_extraction.py) |
| 4 | Visualisation | [`visualize.py`](src/visualize.py) |
| 5 | Analysis & interpretation | [`report.md`](report.md) |

Supporting modules: [`config.py`](src/config.py) (all paths/parameters),
[`pipeline.py`](src/pipeline.py) (orchestration), and
[`artifact_diagnostics.py`](src/artifact_diagnostics.py) (artifact analysis).

**Design principles**
- *Single source of truth* — every path and tunable lives in `config.py`.
- *Pure, testable stages* — each stage reads files / returns arrays and can run
  standalone (`python src/<stage>.py`).
- *Reproducibility* — deterministic; a clean run reproduces identical outputs.
- *Honesty over accuracy* — methods are robust and clearly bounded; artifacts
  and caveats are documented rather than hidden.

---

## 2. Architecture & data flow

```
            inputs/aoi.geojson
                    │ (AOI overlay only)
                    ▼
  data/sentinel2_20230812/{B02,B03,B04}.tif ┐
  data/sentinel2_20230902/{B02,B03,B04}.tif ┘
                    │
        ┌───────────▼─────────────┐
        │ PART 1  data_preparation │  read • verify CRS/transform/dims • stack
        └───────────┬─────────────┘
                    │  data/processed/sentinel2_*_stack.tif   (3-band, uint16)
        ┌───────────▼─────────────┐
        │ PART 2  change_detection │  reflectance • CVA magnitude • robust thresh
        └───────────┬─────────────┘
                    │  change_map.tif (float32 0–1) • change_binary.tif (uint8)
                    │  change_map_example.tif (baseline)
        ┌───────────▼─────────────┐
        │ PART 3  feature_extract  │  polygonise • area + zonal confidence • store
        └───────────┬─────────────┘
                    │  data/processed/changes.gpkg  (SQLite, layer change_features)
        ┌───────────▼─────────────┐
        │ PART 4  visualize        │  static PNG • before/after swipe HTML
        └───────────┬─────────────┘
                    │  outputs/change_overview.png • change_map.html
                    ▼
              report.md  (Part 5, human-written interpretation)
```

`pipeline.py` calls the four stages in order. Each arrow is a file on disk, so
stages are independently runnable and inspectable.

---

## 3. Repository layout

```
.
├── README.md                 Quick start, approach, assumptions
├── DOCUMENTATION.md          This file
├── report.md                 Part 5 — method / results / interpretation
├── requirements.txt          Python dependencies
├── .gitignore
├── inputs/
│   ├── aoi.geojson           Area of interest (WGS84 polygon)
│   └── example_change_detection.py   Provided baseline algorithm
├── data/
│   ├── sentinel2_20230812/   B02.tif B03.tif B04.tif  (date 1, before)
│   ├── sentinel2_20230902/   B02.tif B03.tif B04.tif  (date 2, after)
│   └── processed/            Generated; see §10
│       ├── sentinel2_20230812_stack.tif
│       ├── sentinel2_20230902_stack.tif
│       ├── change_map.tif
│       ├── change_binary.tif
│       ├── change_map_example.tif
│       └── changes.gpkg
├── outputs/
│   ├── change_overview.png
│   ├── change_map.html
│   └── artifact_diagnostics.png
└── src/
    ├── config.py             Paths + parameters (single source of truth)
    ├── data_preparation.py   Part 1
    ├── change_detection.py   Part 2
    ├── feature_extraction.py Part 3
    ├── visualize.py          Part 4
    ├── artifact_diagnostics.py  Artifact analysis
    └── pipeline.py           Runs Parts 1–4
```

---

## 4. Installation

**Requirements:** Python 3.10+ (developed on 3.14). The geospatial stack
(`rasterio`, `geopandas`, `shapely`) ships binary wheels, so no system GDAL is
needed on macOS/Linux/Windows.

```bash
python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

| Package | Used for |
|---------|----------|
| `rasterio` | raster I/O, warping, rasterisation, `features.shapes` |
| `geopandas` / `shapely` | vector features, GeoPackage write, geometry ops |
| `numpy` | array maths (CVA, thresholding) |
| `matplotlib` | static figure, PNG encoding for overlays |
| `folium` | interactive Leaflet map + side-by-side plugin |
| `scipy` | Gaussian background filter (optional RRN / diagnostics) |

`scipy` is only needed for the optional RRN step and `artifact_diagnostics.py`;
the core pipeline runs without it.

---

## 5. Running the pipeline

**Everything (Parts 1–4):**
```bash
python src/pipeline.py
```

**Individual stages** (each writes its inputs' outputs to `data/processed/`):
```bash
python src/data_preparation.py    # Part 1 — stacks
python src/change_detection.py    # Part 2 — change_map / change_binary
python src/feature_extraction.py  # Part 3 — changes.gpkg
python src/visualize.py           # Part 4 — PNG + HTML
python src/artifact_diagnostics.py# artifact analysis figure
```

> Run stages from the repo root as shown, or from inside `src/` — modules import
> `config` by name and resolve all paths relative to the project root, so both
> work. Stages 2–4 expect the outputs of earlier stages to exist.

Expected console summary (default config):
```
Robust threshold (reflectance units): 0.1174
Changed pixels: 23,208 of 2,645,712 valid (0.88%)
Stored 156 features in changes.gpkg (layer 'change_features')
Total changed area: 185.8 ha
```

---

## 6. Configuration reference

All in [`src/config.py`](src/config.py).

| Name | Default | Meaning |
|------|---------|---------|
| `DATE_BEFORE` / `DATE_AFTER` | `"20230812"` / `"20230902"` | Scene folder date stamps; order = before→after |
| `BANDS` | `["B02","B03","B04"]` | Bands loaded & stacked, in order |
| `BAND_NAMES` | Blue/Green/Red | Human labels written into GeoTIFF band descriptions |
| `REFLECTANCE_SCALE` | `10000.0` | DN→reflectance divisor (Sentinel-2 L2A convention) |
| `THRESHOLD_K` | `3.0` | Robust-threshold multiplier: `median + k·1.4826·MAD` |
| `REMOVE_BACKGROUND` | `False` | Enable Relative Radiometric Normalization (artifact removal) |
| `BACKGROUND_SIGMA` | `100` | Gaussian σ (px, ~1 km) for the RRN background estimate |
| `MIN_POLYGON_AREA_M2` | `2000.0` | Drop change polygons smaller than this (speckle filter) |
| `*_PATH`, `*_DIR` | — | Derived input/output paths |
| `CHANGE_TABLE` | `"change_features"` | DB layer/table name |

Tuning notes:
- **More/fewer detections:** lower/raise `THRESHOLD_K` (≈2 = sensitive, ≈4 =
  conservative).
- **Remove the diagonal seam from the intensity map:** set
  `REMOVE_BACKGROUND = True` and raise `THRESHOLD_K` to ~5 (see §12).
- **Coarser/finer polygons:** raise/lower `MIN_POLYGON_AREA_M2`.

---

## 7. Input data specification

**Sentinel-2 bands** (`data/sentinel2_<date>/B0{2,3,4}.tif`):

| Property | Value |
|----------|-------|
| Bands | B02 Blue, B03 Green, B04 Red (10 m optical) |
| CRS | EPSG:32735 (UTM zone 35S) |
| Pixel size | 10 m × 10 m |
| Dimensions | 1673 × 1597 (W × H) |
| Dtype | `uint16` |
| Nodata | `0` |
| Encoding | L2A surface reflectance, DN = reflectance × 10000 |

Both dates share an identical grid (CRS + affine transform + size) — i.e. the
scenes are already **co-registered**, which Part 1 asserts before stacking.

**AOI** (`inputs/aoi.geojson`): a single WGS84 (EPSG:4326) rectangular polygon
over the mine, used purely as a visual overlay. Its corners are ~25.79–25.94°E,
−12.32 to −12.18°S.

---

## 8. Module reference

### 8.1 `config.py`
Constants only — no logic. Imported by every other module so paths/parameters
are defined once. Paths are derived from `ROOT` (the repo root, computed from
the file location) so the pipeline is location-independent.

### 8.2 `data_preparation.py` — Part 1
| Function | Purpose |
|----------|---------|
| `load_and_check_scene(date)` | Reads B02/B03/B04 for one date; asserts every band shares the same `(crs, transform, (h,w))`; returns `(stack[3,h,w] uint16, profile)` |
| `write_stack(stack, profile, path)` | Writes a 3-band deflate-compressed GeoTIFF, tagging band descriptions |
| `prepare()` | Runs both dates, writes the stacks, and asserts the two dates lie on the **same grid** (co-registration). Returns `{date: (stack, profile)}` |

Raises `ValueError` on any intra-scene grid mismatch or inter-date grid
mismatch — failing loud rather than silently mis-aligning the change maths.

### 8.3 `change_detection.py` — Part 2
| Function | Purpose |
|----------|---------|
| `_read_stack(path)` | Read a stack as `float32 (3,h,w)` + profile |
| `_valid_mask(before, after)` | Boolean mask: pixels with DN>0 in **all** bands of **both** dates |
| `remove_background(diff, valid, sigma)` | Optional RRN: subtract a nodata-aware Gaussian background from each band-difference (lazy-imports `scipy`) |
| `robust_threshold(values, k)` | `median + k·1.4826·MAD` (see §9.2) |
| `detect_change()` | Orchestrates Part 2; writes `change_map.tif`, `change_binary.tif`, `change_map_example.tif`; returns a dict of arrays |
| `_write(path, array, profile, dtype, nodata)` | Single-band GeoTIFF writer |

`detect_change()` flow: read stacks → valid mask → reflectance → (optional RRN)
→ CVA magnitude → robust threshold → binary mask → normalised intensity →
write rasters → apply provided baseline for comparison.

### 8.4 `feature_extraction.py` — Part 3
| Function | Purpose |
|----------|---------|
| `extract_features()` | Polygonise `change_binary.tif`; drop polygons < `MIN_POLYGON_AREA_M2`; compute `area_m2` and zonal `confidence`; write `changes.gpkg`. Returns a `GeoDataFrame` |
| `_zonal_mean(polygons, intensity, transform)` | Mean `change_map` intensity inside each polygon (rasterised mask) → confidence |
| `_fmt_date(yyyymmdd)` | `"20230812"` → `"2023-08-12"` |

Polygons are built with `rasterio.features.shapes` on the `==1` class. Because
the CRS is metric UTM, `shapely`'s `.area` is already in m². Features are sorted
by area (descending) and given a 1-based `id`.

### 8.5 `visualize.py` — Part 4
| Function | Purpose |
|----------|---------|
| `_rgb(path)` | B/G/R stack → 2–98 % contrast-stretched RGB array (for the static figure) |
| `_rgb_overlay_4326(path, max_px=1100)` | Reproject stack to EPSG:4326, stretch, encode a transparent-nodata PNG, return `(data-URI, [[S,W],[N,E]])` for a Leaflet `ImageOverlay` |
| `static_overview(gdf)` | 4-panel `change_overview.png`: before RGB, after RGB, change intensity, polygons-on-AOI |
| `interactive_map(gdf)` | Builds `change_map.html` — before/after swipe + change/AOI layers |
| `visualize()` | Runs both |

**Swipe map internals.** Two `ImageOverlay`s (before, after) at identical WGS84
bounds are driven by the `leaflet-side-by-side` plugin (Folium
`SideBySideLayers`). That plugin calls `getContainer()` on each layer, which
`TileLayer` has but `ImageOverlay` does not (it exposes `getElement()`); the
missing method throws and aborts the rest of the page script. A one-line
injected patch aliases it:
```js
L.ImageOverlay.prototype.getContainer = L.ImageOverlay.prototype.getElement;
```
added via a `MacroElement` *before* the side-by-side control so it executes
first. Change polygons and the AOI are added as toggleable overlay layers in a
`LayerControl`; the basemap and the two RGB overlays are `control=False` (driven
by the slider, not the toggle list).

### 8.6 `artifact_diagnostics.py`
Standalone analysis of the diagonal seam (see §12). Prints per-band difference
statistics and the threshold-vs-seam ratio, and writes
`outputs/artifact_diagnostics.png` (before/after brightness vs change magnitude
vs RRN-flattened magnitude). Reuses `remove_background` and `robust_threshold`
from the detection module so the diagnostic matches the pipeline exactly.

### 8.7 `pipeline.py`
Imports and calls `prepare → detect_change → extract_features → visualize` with
banner logging. The single entry point for a full reproducible run.

---

## 9. Algorithms in depth

### 9.1 Change Vector Analysis (CVA)
For each pixel, with before/after reflectance vectors **b**, **a** over the 3
bands:

```
diff = a − b                       # per-band change, shape (3,h,w)
magnitude(x,y) = ‖diff(x,y)‖₂ = sqrt( Σ_band diff² )
```

`magnitude` is the per-pixel **change intensity**. Using all three bands at once
captures both brightness and colour change; with only B/G/R (no NIR), a
vegetation index like NDVI is not computable, so a multi-band magnitude is the
most information-rich unsupervised option.

Reflectance conversion (`DN/10000`) makes the magnitude physically meaningful
and comparable between dates.

### 9.2 Robust thresholding
A pixel is *changed* when its magnitude exceeds

```
T = median(magnitude) + k · 1.4826 · MAD(magnitude)        k = THRESHOLD_K = 3
MAD = median(|magnitude − median(magnitude)|)
```

- `1.4826 · MAD` is a robust estimate of σ for normal data, so `k` behaves like
  a sigma multiplier (k=3 ≈ a 3-sigma outlier rule).
- median/MAD are used **instead of** mean/std or Otsu because the magnitude
  histogram is dominated by a scene-wide illumination/atmosphere offset
  (median ≈ 0.047 here). Mean/std are dragged by the heavy change tail; Otsu
  split the near-unimodal bulk and over-detected ~48 % of the scene. median/MAD
  isolates the statistically anomalous tail → 0.88 %.

### 9.3 Intensity normalisation (for visualisation & confidence)
```
hi = 99.9th percentile of magnitude over valid pixels
intensity = clip(magnitude / hi, 0, 1)          # float32, 0–1
```
The 99.9th-percentile cap (rather than the max) is robust to a few extreme
pixels, and sits *above* the change threshold so genuine-change pixels spread
across ~0.5–1.0 — which makes the per-polygon mean-intensity **confidence**
actually discriminate weak from strong change (observed range 0.56–0.91).

### 9.4 Relative Radiometric Normalization (optional, `remove_background`)
```
background_band = gaussian(diff_band · valid, σ) / gaussian(valid, σ)   # nodata-aware
diff_band ← diff_band − background_band
```
A large-σ (≈1 km) smooth background captures the low-frequency additive bias
(global offset + detector seam) while leaving compact real change intact. Off by
default — see §12 for the trade-off.

### 9.5 Provided baseline (`example_change_detection.compute_change_distance`)
Euclidean distance on **raw DN** with global **min–max** normalisation to
0–255. Applied unchanged and saved as `change_map_example.tif`. It is the same
distance concept but more fragile: a single bright outlier stretches the min–max
scale and collapses real signal toward zero. The pipeline improves on it with
reflectance scaling and an outlier-robust threshold, and adds the binary +
vector products the baseline lacks.

### 9.6 Polygonisation & zonal confidence
`rasterio.features.shapes` traces the `binary==1` class into polygons (in the
raster CRS). Polygons below `MIN_POLYGON_AREA_M2` are dropped. For each kept
polygon, `_zonal_mean` rasterises it to a mask and averages `change_map`
intensity inside → `confidence`.

---

## 10. Output specification

All under `data/processed/` and `outputs/`.

| File | Format | CRS | Dtype / content |
|------|--------|-----|-----------------|
| `sentinel2_<date>_stack.tif` | GeoTIFF, 3-band, deflate | EPSG:32735 | uint16; Blue/Green/Red |
| `change_map.tif` | GeoTIFF, 1-band | EPSG:32735 | float32 0–1 change intensity |
| `change_binary.tif` | GeoTIFF, 1-band | EPSG:32735 | uint8: 1=change, 0=no change (nodata 255) |
| `change_map_example.tif` | GeoTIFF, 1-band | EPSG:32735 | uint8 0–255 baseline (nodata 0) |
| `changes.gpkg` | GeoPackage (SQLite) | EPSG:32735 | layer `change_features` (§11) |
| `change_overview.png` | PNG | — | 4-panel static figure |
| `change_map.html` | HTML | EPSG:4326 overlays | before/after swipe + layers |
| `artifact_diagnostics.png` | PNG | — | seam analysis figure |

Large reproducible rasters are git-ignored; `changes.gpkg` and the `outputs/`
figures are committed as deliverables.

---

## 11. Database schema & queries

`changes.gpkg` is an OGC **GeoPackage** — itself a SQLite database with a true
geometry type — satisfying the "SQLite, geometry stored as geometry type"
requirement. Open it in QGIS, GeoPandas/Fiona, the `sqlite3` CLI, or any
SpatiaLite-aware tool.

**Table `change_features`:**

| Column | Type | Description |
|--------|------|-------------|
| `fid` | INTEGER | GeoPackage primary key (auto) |
| `id` | INTEGER | 1-based feature id (area-sorted) |
| `date_before` | TEXT | `YYYY-MM-DD` of the earlier scene |
| `date_after` | TEXT | `YYYY-MM-DD` of the later scene |
| `area_m2` | REAL | Polygon area in m² (metric UTM CRS) |
| `confidence` | REAL | Mean change intensity 0–1 inside the polygon |
| `geom` | POLYGON | Geometry, EPSG:32735 |

**Example queries:**
```bash
# Top-5 largest changes
sqlite3 data/processed/changes.gpkg \
  "SELECT id, area_m2, confidence FROM change_features ORDER BY area_m2 DESC LIMIT 5;"

# Total changed area (hectares)
sqlite3 data/processed/changes.gpkg \
  "SELECT ROUND(SUM(area_m2)/10000.0, 1) AS total_ha FROM change_features;"
```
```python
import geopandas as gpd
gdf = gpd.read_file("data/processed/changes.gpkg", layer="change_features")
print(gdf[["id", "area_m2", "confidence"]].head())
```

---

## 12. The diagonal artifact

Full treatment in [report.md §4](report.md#4-the-diagonal-artifact--diagnosis-and-removal);
reproduce with `python src/artifact_diagnostics.py`.

- **What:** a faint diagonal in the change-intensity map — a Sentinel-2
  detector-module seam plus a global illumination/atmosphere offset. It lives
  *only in the difference* (both single-date brightness images are smooth).
- **Impact:** none on the result. The seam bias sits at magnitude ≈ 0.047; the
  robust threshold is 0.117 (**2.5× higher**), so the seam never enters the
  binary detections — polygons cluster on the mine, none along the diagonal.
- **Removal options:** robust threshold + min-area filter (in use) already
  neutralise it. Relative Radiometric Normalization (`REMOVE_BACKGROUND`)
  flattens the seam visually but lowers the noise floor and over-detects texture
  (0.88 %→3.6 %, 156→494 polygons) — off by default. The production-grade fix is
  a detector-footprint mask (`MSK_DETFOO` in the SAFE metadata), not available
  for the clipped bands provided here.

---

## 13. Results summary

| Metric | Value |
|--------|-------|
| Valid pixels compared | 2,645,712 |
| Robust threshold (reflectance) | 0.1174 |
| Changed pixels | 23,208 (0.88 %) |
| Change polygons (≥ 2000 m²) | 156 |
| Total changed area | 185.8 ha |
| Polygon area: median / max | 0.45 ha / 33 ha |
| Confidence: min / mean / max | 0.56 / 0.71 / 0.91 |

Change concentrates on the active pit faces/benches, the tailings/processing
area, and the edges of pit lakes/ponds — consistent with ~3 weeks of open-pit
mining. Surrounding bushland is almost entirely no-change (dry season).

---

## 14. Design decisions & trade-offs

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| CVA over NDVI | No NIR band provided → NDVI impossible; CVA uses all 3 bands | Not vegetation-specific |
| Reflectance (÷10000) | Physically comparable differences | Assumes L2A scaling |
| median/MAD threshold | Robust to the heavy change tail & scene-wide drift; unsupervised | Single global threshold (not spatially adaptive by default) |
| 99.9th-pctile intensity cap | Makes per-polygon confidence discriminative | Slightly dims the intensity display |
| RRN off by default | Global threshold already excludes the seam; RRN adds texture noise | Diagonal remains visible in the intensity *picture* |
| GeoPackage as the DB | SQLite + true geometry type, portable, no server | Not PostGIS (fine for this scale) |
| Min-area 2000 m² | Removes speckle / sub-feature noise | May drop genuine very small changes |
| Embedded PNG overlays in HTML | Self-contained, portable file | ~6.5 MB HTML |

---

## 15. Extending the pipeline

- **Different dates/site:** drop new `data/sentinel2_<date>/` folders and update
  `DATE_BEFORE`/`DATE_AFTER` in `config.py`. Everything else is parameterised.
- **More bands (e.g. add NIR for NDVI):** extend `BANDS`/`BAND_NAMES`; CVA scales
  to any band count automatically. Add an NDVI branch in `detect_change()`.
- **PostGIS instead of GeoPackage:** replace the `gdf.to_file(GPKG_PATH, ...)`
  call in `feature_extraction.py` with `gdf.to_postgis("change_features",
  engine, ...)` (SQLAlchemy connection).
- **Cloud masking:** add a mask step in Part 1 (e.g. from the SCL band) and fold
  it into `_valid_mask`.
- **Adaptive thresholding:** enable `REMOVE_BACKGROUND` and/or replace the global
  `robust_threshold` with a local windowed z-score for spatially-varying scenes.

---

## 16. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `ModuleNotFoundError: rasterio` | Activate the venv and `pip install -r requirements.txt` |
| `ValueError: Grid mismatch …` | A band's CRS/transform/size differs — inputs not co-registered; re-clip/resample to a common grid first |
| `scipy` import error | Only needed for `REMOVE_BACKGROUND` / diagnostics: `pip install scipy` |
| Change % is huge (≈50 %) | Threshold too low — this is the Otsu failure mode; the default median/MAD avoids it |
| `change_map.html` blank / no swipe | Open the file directly in a browser (GitHub won't preview large HTML); needs internet for the Leaflet/basemap CDNs |
| Layer control missing in the map | The `ImageOverlay.getContainer` patch must run before the side-by-side control — preserved in `interactive_map()` |
| Confidence all = 1.0 | Intensity cap too low; the 99.9th-percentile cap (default) fixes it |

---

## 17. Limitations & future work

- **No cloud/shadow mask** — thin cloud or shadow edges would register as
  change. The AOI looks clear here. Adding an SCL-based mask is the main
  robustness upgrade.
- **Confidence is relative**, not a calibrated probability.
- **Single global threshold** by default — a spatially-adaptive (local) threshold
  would handle scenes with strong illumination gradients better.
- **Detector seam** is suppressed, not removed at source — full SAFE metadata
  would allow a proper `MSK_DETFOO` mask.
- **Two-date only** — multi-temporal stacking would separate persistent change
  from transient noise and seasonal cycles.
