# Sentinel-2 Change Analysis — Open-Pit Mine, Zambia

A small geospatial analytics pipeline that detects, stores, visualises and
interprets land-surface change between two Sentinel-2 acquisitions
(**2023-08-12** → **2023-09-02**) over an open-pit mining site in Zambia.

The pipeline covers the five parts of the assignment:

| Part | Stage | Module | Output |
|------|-------|--------|--------|
| 1 | Data preparation | [`src/data_preparation.py`](src/data_preparation.py) | `data/processed/sentinel2_*_stack.tif` |
| 2 | Change detection | [`src/change_detection.py`](src/change_detection.py) | `change_map.tif`, `change_binary.tif` |
| 3 | Feature extraction + storage | [`src/feature_extraction.py`](src/feature_extraction.py) | `changes.gpkg` (SQLite) |
| 4 | Visualisation | [`src/visualize.py`](src/visualize.py) | `outputs/change_overview.png`, `change_map.html` |
| 5 | Analysis & interpretation | [`report.md`](report.md) | — |

📖 **Full engineering reference:** [DOCUMENTATION.md](DOCUMENTATION.md) — architecture,
module-by-module API, algorithm maths, output/DB specs, configuration, design
decisions, and troubleshooting.

---

## How to run

```bash
# 1. Create an environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Run the whole pipeline (Parts 1–4)
python src/pipeline.py
```

Each stage can also be run on its own, e.g. `python src/change_detection.py`.
All paths and tunable parameters live in [`src/config.py`](src/config.py).

### Inputs expected

```
inputs/
  aoi.geojson                       # Area of interest (WGS84)
  example_change_detection.py       # Provided baseline algorithm
data/
  sentinel2_20230812/  B02.tif B03.tif B04.tif   # Blue, Green, Red (date 1)
  sentinel2_20230902/  B02.tif B03.tif B04.tif   # date 2
```

### Outputs produced

```
data/processed/
  sentinel2_20230812_stack.tif      # 3-band stack, date 1
  sentinel2_20230902_stack.tif      # 3-band stack, date 2
  change_map.tif                    # continuous change intensity (float32, 0–1)
  change_binary.tif                 # change / no-change mask (uint8)
  change_map_example.tif            # provided baseline method, for comparison
  changes.gpkg                      # SQLite/GeoPackage DB — table `change_features`
outputs/
  change_overview.png               # static 4-panel figure
  change_map.html                   # interactive Folium map
  artifact_diagnostics.png          # detector-seam artifact analysis
```

---

## Approach

### Part 1 — Data preparation
Bands 2/3/4 are read for both dates. Before stacking, the loader asserts that
**CRS, affine transform and dimensions are identical** across all six rasters
(they are: EPSG:32735 / UTM 35S, 10 m, 1673×1597), and that both dates lie on
the same grid — i.e. the scenes are already co-registered, which change
detection requires. Each date is written as a 3-band `*_stack.tif`.

### Part 2 — Change detection
The primary method is **Change Vector Analysis (CVA)**:

1. Convert DN → surface reflectance (`DN / 10000`).
2. Per-pixel spectral change magnitude = Euclidean norm of the
   (after − before) vector across the 3 bands.
3. Binary mask via a **robust statistical threshold**:
   `median + 3 · 1.4826 · MAD` of the magnitude over valid pixels.

Working in reflectance and thresholding with median/MAD (rather than a
hand-picked cut-off, Otsu, or mean/std) isolates the *statistically anomalous
tail* of real change while ignoring the scene-wide illumination/atmospheric
drift that shifts every pixel slightly between the two dates. Pixels that are
nodata (DN = 0) in any band of either date are excluded throughout.

The provided Euclidean-distance baseline
(`inputs/example_change_detection.py`) is also applied and saved as
`change_map_example.tif` for comparison — see [`report.md`](report.md).

### Part 3 — Feature extraction & storage
The binary mask is polygonised (`rasterio.features.shapes`), polygons smaller
than 2000 m² (~20 pixels) are dropped as speckle, and each polygon gets a
`confidence` = mean change intensity of the pixels it covers. Features are
written to **`changes.gpkg`**, a GeoPackage — which is itself a SQLite database
with a true geometry column, satisfying the "SQLite, geometry stored as
geometry type" requirement. It opens in QGIS, GeoPandas/Fiona, the `sqlite3`
CLI, or any SpatiaLite-aware tool.

Table `change_features`:

| id | date_before | date_after | area_m2 | confidence | geom |
|----|-------------|------------|---------|------------|------|
| 1  | 2023-08-12  | 2023-09-02 | …       | 0–1        | POLYGON (EPSG:32735) |

Inspect it directly:
```bash
sqlite3 data/processed/changes.gpkg \
  "SELECT id, area_m2, confidence FROM change_features ORDER BY area_m2 DESC LIMIT 5;"
```

> Note: areas are computed in the metric UTM projection, so `area_m2` is in
> true square metres.

### Part 4 — Visualisation
`change_overview.png` shows before/after RGB, the change-intensity map, and the
extracted polygons over the AOI. `change_map.html` is an interactive Folium map
with a **before/after swipe slider** (Before RGB in the left pane, After RGB in
the right), the detected change polygons overlaid on top (shaded by confidence),
plus a layer control to toggle the change and AOI layers on/off.

---

## Artifact handling (diagonal detector seam)
The change-intensity map shows a faint diagonal — a Sentinel-2 detector-module
seam plus a global illumination offset, **not** ground change. Run
`python src/artifact_diagnostics.py` for the analysis figure. Key point: the
global robust threshold (0.117) sits 2.5× above the seam bias (0.047), so the
seam never enters the detected polygons. A Relative Radiometric Normalization
step is implemented and available via `config.REMOVE_BACKGROUND = True` (off by
default — it cleans the picture but over-detects texture). Full diagnosis,
options table and the production fix (detector-footprint mask) are in
[`report.md`](report.md#4-the-diagonal-artifact--diagnosis-and-removal).

## Assumptions
- The three bands are Sentinel-2 L2A **surface reflectance** scaled by 10000;
  hence the `/10000` conversion. (If they were L1C TOA the relative CVA result
  would be similar; only the absolute threshold value would shift.)
- DN = 0 is treated as nodata.
- The two scenes are co-registered (verified in Part 1), so no resampling /
  alignment step is needed.
- "Confidence" is a relative change-strength score (normalised magnitude),
  not a calibrated probability.

## Project layout
```
src/            pipeline modules + config
inputs/         AOI + provided example algorithm
data/           input scenes and (generated) data/processed artefacts
outputs/        figures and interactive map
report.md       Part 5 — method, results, interpretation
```
