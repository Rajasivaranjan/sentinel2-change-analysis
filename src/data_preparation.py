"""PART 1 - Data preparation.

Load Bands 2/3/4 for both dates, verify that CRS, transform and dimensions are
consistent across every band, and stack the three bands into a single
multi-band GeoTIFF per date.
"""
from __future__ import annotations

import numpy as np
import rasterio

from config import BANDS, BAND_NAMES, PROCESSED_DIR, SCENE_DIRS, STACK_PATHS


def _band_path(date: str, band: str):
    return SCENE_DIRS[date] / f"{band}.tif"


def load_and_check_scene(date: str):
    """Read the three bands for one date and confirm they share a grid.

    Returns
    -------
    stack : np.ndarray, shape (bands, height, width), dtype uint16
    profile : dict
        A rasterio profile describing the (shared) grid, ready to be reused
        for writing the stacked output.
    """
    arrays = []
    reference = None  # (crs, transform, shape) of the first band read

    for band in BANDS:
        path = _band_path(date, band)
        with rasterio.open(path) as src:
            signature = (src.crs, src.transform, (src.height, src.width))
            if reference is None:
                reference = signature
                profile = src.profile.copy()
            elif signature != reference:
                raise ValueError(
                    f"Grid mismatch for {date}/{band}: {signature} != {reference}"
                )
            arrays.append(src.read(1))
            print(
                f"  {date} {band} ({BAND_NAMES[band]:>5}) "
                f"crs={src.crs} size={src.width}x{src.height} dtype={src.dtypes[0]}"
            )

    stack = np.stack(arrays, axis=0)
    profile.update(count=len(BANDS))
    return stack, profile


def write_stack(stack: np.ndarray, profile: dict, path) -> None:
    profile = profile.copy()
    profile.update(driver="GTiff", compress="deflate")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(stack)
        for idx, band in enumerate(BANDS, start=1):
            dst.set_band_description(idx, BAND_NAMES[band])


def prepare() -> dict:
    """Run Part 1 and return the in-memory stacks keyed by date."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    stacks = {}

    print("PART 1 - loading and stacking Sentinel-2 bands")
    grids = []
    for date in SCENE_DIRS:
        stack, profile = load_and_check_scene(date)
        write_stack(stack, profile, STACK_PATHS[date])
        stacks[date] = (stack, profile)
        grids.append((profile["crs"], profile["transform"], stack.shape[1:]))
        print(f"  -> wrote {STACK_PATHS[date].name}\n")

    # Cross-date consistency: change detection requires co-registered scenes.
    if grids[0] != grids[1]:
        raise ValueError(
            "The two dates are not on the same grid - co-registration required."
        )
    print("  Both dates share an identical grid (co-registered). OK\n")
    return stacks


if __name__ == "__main__":
    prepare()
