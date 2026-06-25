"""Central configuration for the Sentinel-2 change-analysis pipeline.

Keeping all paths and tunable parameters in one place makes the individual
pipeline stages easy to read and the whole run reproducible.
"""
from pathlib import Path

# --- Project layout -------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent

INPUTS_DIR = ROOT / "inputs"
DATA_DIR = ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
OUTPUTS_DIR = ROOT / "outputs"

AOI_PATH = INPUTS_DIR / "aoi.geojson"

# The two acquisition dates we compare. Order matters: "before" then "after".
DATE_BEFORE = "20230812"
DATE_AFTER = "20230902"

SCENE_DIRS = {
    DATE_BEFORE: DATA_DIR / f"sentinel2_{DATE_BEFORE}",
    DATE_AFTER: DATA_DIR / f"sentinel2_{DATE_AFTER}",
}

# Bands provided for each scene, in the order we stack them.
# Sentinel-2 10 m optical bands: Blue, Green, Red.
BANDS = ["B02", "B03", "B04"]
BAND_NAMES = {"B02": "Blue", "B03": "Green", "B04": "Red"}

# --- Generated artefacts --------------------------------------------------
STACK_PATHS = {
    DATE_BEFORE: PROCESSED_DIR / f"sentinel2_{DATE_BEFORE}_stack.tif",
    DATE_AFTER: PROCESSED_DIR / f"sentinel2_{DATE_AFTER}_stack.tif",
}
CHANGE_MAP_PATH = PROCESSED_DIR / "change_map.tif"            # continuous intensity
CHANGE_BINARY_PATH = PROCESSED_DIR / "change_binary.tif"      # 0 / 1 change mask
EXAMPLE_CHANGE_PATH = PROCESSED_DIR / "change_map_example.tif"  # baseline method
GPKG_PATH = PROCESSED_DIR / "changes.gpkg"                    # SQLite/GeoPackage DB
CHANGE_TABLE = "change_features"

# --- Algorithm parameters -------------------------------------------------
# Sentinel-2 L2A surface reflectance is stored as DN scaled by 10000.
REFLECTANCE_SCALE = 10000.0

# Robust change threshold: a pixel is "changed" when its spectral change
# magnitude exceeds  median + THRESHOLD_K * 1.4826 * MAD  of the scene.
# Using median/MAD (instead of Otsu or mean/std) isolates the statistically
# anomalous tail while ignoring the scene-wide illumination/atmospheric drift
# that affects every pixel between the two dates. k=3 ~ a 3-sigma outlier rule.
THRESHOLD_K = 3.0

# --- Artifact handling (Relative Radiometric Normalization) ---------------
# The difference image carries a smooth, low-frequency additive bias: a global
# illumination/atmosphere offset plus a Sentinel-2 detector-module seam (the
# faint diagonal in the change-intensity map). See src/artifact_diagnostics.py.
#
# REMOVE_BACKGROUND subtracts a large-scale smooth background from each band
# difference (RRN) so that bias is flattened before computing the magnitude.
# It is OFF by default: the global robust threshold already sits ABOVE the
# seam's bias, so the seam never enters the binary detections, and turning RRN
# on lowers the noise floor and over-detects vegetation texture / co-
# registration edges. Enable it only for low/local-threshold analysis, and
# raise THRESHOLD_K (~5) to compensate.
REMOVE_BACKGROUND = False
BACKGROUND_SIGMA = 100  # px; ~1 km smoothing window for the background estimate

# Minimum mapped change-polygon area (m^2). At 10 m resolution one pixel is
# 100 m^2; 2000 m^2 (~20 pixels) drops speckle while keeping real features.
MIN_POLYGON_AREA_M2 = 2000.0
