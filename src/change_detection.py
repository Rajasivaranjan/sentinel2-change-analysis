"""PART 2 - Change detection.

Two methods are produced:

1. **Change Vector Analysis (CVA)** - my own method. Bands are first converted
   from raw DN to surface reflectance, the per-pixel spectral change magnitude
   is computed, and the binary change mask is derived with a data-driven Otsu
   threshold rather than a hand-picked cut-off. This is the primary output.

2. **Euclidean spectral distance** - the provided baseline
   (`inputs/example_change_detection.py`), applied for comparison.

Working in reflectance + an automatic threshold makes the result less
sensitive to absolute brightness and outliers than the raw min-max baseline.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import rasterio

sys.path.append(str(Path(__file__).resolve().parent.parent / "inputs"))
from example_change_detection import compute_change_distance  # noqa: E402

from config import (  # noqa: E402
    BACKGROUND_SIGMA,
    CHANGE_BINARY_PATH,
    CHANGE_MAP_PATH,
    DATE_AFTER,
    DATE_BEFORE,
    EXAMPLE_CHANGE_PATH,
    REFLECTANCE_SCALE,
    REMOVE_BACKGROUND,
    STACK_PATHS,
    THRESHOLD_K,
)


def _read_stack(path):
    with rasterio.open(path) as src:
        data = src.read().astype(np.float32)  # (bands, h, w)
        profile = src.profile.copy()
    return data, profile


def _valid_mask(before_dn, after_dn):
    """Pixels that are valid (non-zero) in every band of both dates."""
    return np.all(before_dn > 0, axis=0) & np.all(after_dn > 0, axis=0)


def remove_background(diff: np.ndarray, valid: np.ndarray, sigma: float) -> np.ndarray:
    """Relative Radiometric Normalization of the band-difference cube.

    Subtracts a large-scale smooth background (a nodata-aware Gaussian, i.e.
    normalized convolution) from each band difference. This flattens the
    low-frequency additive bias - the global illumination/atmosphere offset and
    the Sentinel-2 detector-module seam - while leaving compact, high-frequency
    real change (pit faces, tailings) intact.
    """
    from scipy.ndimage import gaussian_filter  # optional dependency, lazy import

    vf = valid.astype(np.float32)
    denom = gaussian_filter(vf, sigma)
    denom[denom < 1e-6] = 1e-6
    out = np.empty_like(diff)
    for i in range(diff.shape[0]):
        masked = np.where(valid, diff[i], 0.0)
        background = gaussian_filter(masked, sigma) / denom
        out[i] = diff[i] - background
    return out


def robust_threshold(values: np.ndarray, k: float = THRESHOLD_K) -> float:
    """Robust outlier threshold:  median + k * 1.4826 * MAD.

    The 1.4826 factor scales the Median Absolute Deviation to a standard-
    deviation equivalent for normally distributed data, so ``k`` behaves like a
    sigma multiplier but is far less sensitive to the heavy tail of genuine
    change pixels than mean/std would be.
    """
    median = np.median(values)
    mad = np.median(np.abs(values - median))
    return float(median + k * 1.4826 * mad)


def detect_change():
    """Run both detectors, write the rasters, and return arrays for later use."""
    print("PART 2 - change detection (CVA, reflectance + robust threshold)")
    before_dn, profile = _read_stack(STACK_PATHS[DATE_BEFORE])
    after_dn, _ = _read_stack(STACK_PATHS[DATE_AFTER])

    valid = _valid_mask(before_dn, after_dn)

    # --- My method: Change Vector Analysis on surface reflectance ----------
    before = before_dn / REFLECTANCE_SCALE
    after = after_dn / REFLECTANCE_SCALE
    diff = after - before

    # Optional artifact removal (off by default - see config.REMOVE_BACKGROUND).
    if REMOVE_BACKGROUND:
        diff = remove_background(diff, valid, BACKGROUND_SIGMA)
        print(f"  Relative radiometric normalization applied (sigma={BACKGROUND_SIGMA})")

    magnitude = np.sqrt(np.sum(diff ** 2, axis=0)).astype(np.float32)  # (h, w)
    magnitude[~valid] = 0.0

    # Data-driven threshold from the valid-pixel magnitude distribution.
    threshold = robust_threshold(magnitude[valid])
    binary = ((magnitude > threshold) & valid).astype(np.uint8)

    # Continuous change-intensity map, normalised 0-1 over valid pixels and
    # robust to outliers (clip at the 99.9th percentile before scaling). This
    # upper bound sits above the change threshold, so genuine-change pixels
    # spread across ~0.5-1.0 and the per-polygon confidence (mean intensity)
    # actually discriminates weak from strong change.
    hi = np.percentile(magnitude[valid], 99.9)
    intensity = np.clip(magnitude / hi, 0, 1).astype(np.float32) if hi > 0 else magnitude
    intensity[~valid] = 0.0

    pct = 100.0 * binary.sum() / valid.sum()
    print(f"  Robust threshold (reflectance units): {threshold:.4f}")
    print(f"  Changed pixels: {binary.sum():,} of {valid.sum():,} valid ({pct:.2f}%)")

    _write(CHANGE_MAP_PATH, intensity, profile, dtype="float32", nodata=None)
    _write(CHANGE_BINARY_PATH, binary, profile, dtype="uint8", nodata=255)
    print(f"  -> {CHANGE_MAP_PATH.name}, {CHANGE_BINARY_PATH.name}")

    # --- Baseline: provided Euclidean-distance method ----------------------
    # The example expects (h, w, bands); our arrays are (bands, h, w).
    example_u8, _ = compute_change_distance(
        np.moveaxis(before_dn, 0, -1), np.moveaxis(after_dn, 0, -1)
    )
    example_u8 = example_u8.copy()
    example_u8[~valid] = 0
    _write(EXAMPLE_CHANGE_PATH, example_u8, profile, dtype="uint8", nodata=0)
    print(f"  -> {EXAMPLE_CHANGE_PATH.name} (baseline)\n")

    return {
        "intensity": intensity,
        "binary": binary,
        "magnitude": magnitude,
        "valid": valid,
        "threshold": threshold,
        "profile": profile,
    }


def _write(path, array, profile, dtype, nodata):
    profile = profile.copy()
    profile.update(count=1, dtype=dtype, compress="deflate", nodata=nodata)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array.astype(dtype), 1)


if __name__ == "__main__":
    detect_change()
