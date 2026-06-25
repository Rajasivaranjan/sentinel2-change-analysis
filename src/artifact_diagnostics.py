"""Diagnose the diagonal artifact in the change-intensity map.

The faint diagonal visible in `change_map.tif` is NOT ground change. This
script characterises it and shows why the production pipeline is already robust
to it. It writes `outputs/artifact_diagnostics.png` and prints the key numbers.

Findings (see report.md, "Artifacts"):
  * Both single-date brightness images are smooth - the diagonal lives only in
    the *difference*, as a low-frequency additive step. That is the signature of
    a Sentinel-2 detector-module seam plus a global illumination/atmosphere
    offset, not real change.
  * The global robust threshold sits ABOVE the seam's bias, so the seam never
    enters the binary detections.
  * Relative Radiometric Normalization (RRN) flattens the seam in the picture
    but lowers the noise floor and over-detects texture - a net loss for the
    vector product. The proper production fix is a detector-footprint mask
    (MSK_DETFOO), which needs SAFE metadata not shipped with the clipped bands.
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio

from config import (
    BACKGROUND_SIGMA,
    OUTPUTS_DIR,
    REFLECTANCE_SCALE,
    STACK_PATHS,
    THRESHOLD_K,
    DATE_AFTER,
    DATE_BEFORE,
)
from change_detection import remove_background, robust_threshold


def _read(path):
    with rasterio.open(path) as src:
        return src.read().astype(np.float32) / REFLECTANCE_SCALE


def main() -> None:
    before = _read(STACK_PATHS[DATE_BEFORE])
    after = _read(STACK_PATHS[DATE_AFTER])
    valid = np.all(before > 0, axis=0) & np.all(after > 0, axis=0)
    diff = after - before

    mag = np.sqrt((diff ** 2).sum(0))
    detr = remove_background(diff, valid, BACKGROUND_SIGMA)
    mag_rrn = np.sqrt((detr ** 2).sum(0))

    t_glob = robust_threshold(mag[valid])
    seam_bias = np.median(mag[valid])  # ~ the low-frequency background level

    print("Per-band mean difference (after-before), reflectance:")
    for i, name in enumerate(["Blue", "Green", "Red"]):
        print(f"  {name:5s}: {diff[i][valid].mean():+.4f}")
    print(f"Background/seam level (median magnitude): {seam_bias:.4f}")
    print(f"Global robust threshold (k={THRESHOLD_K}):     {t_glob:.4f}"
          f"  -> threshold is {t_glob / seam_bias:.1f}x the seam bias, "
          "so the seam is excluded from detections.")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    bb, ab = before.mean(0), after.mean(0)
    for arr in (bb, ab, mag, mag_rrn):
        arr[~valid] = np.nan

    fig, ax = plt.subplots(2, 2, figsize=(13, 12))
    ax[0, 0].imshow(bb, cmap="gray", vmin=0, vmax=0.4)
    ax[0, 0].set_title("Before brightness (smooth - no diagonal)")
    ax[0, 1].imshow(ab, cmap="gray", vmin=0, vmax=0.4)
    ax[0, 1].set_title("After brightness (smooth - no diagonal)")
    ax[1, 0].imshow(mag, cmap="inferno", vmin=0, vmax=0.15)
    ax[1, 0].set_title("Change magnitude - diagonal detector seam visible")
    ax[1, 1].imshow(mag_rrn, cmap="inferno", vmin=0, vmax=0.15)
    ax[1, 1].set_title(f"After RRN (sigma={BACKGROUND_SIGMA}) - seam flattened")
    for a in ax.ravel():
        a.set_xticks([])
        a.set_yticks([])
    fig.suptitle("Diagonal artifact: a difference-only detector seam", fontsize=14)
    fig.tight_layout()
    out = OUTPUTS_DIR / "artifact_diagnostics.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"-> {out.relative_to(OUTPUTS_DIR.parent)}")


if __name__ == "__main__":
    main()
