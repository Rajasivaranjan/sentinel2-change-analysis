"""PART 3 - Change feature extraction and storage.

Vectorise the binary change raster into polygons, attach attributes
(area, mean change confidence, the two dates), and persist them to a
geospatial database.

The database is a **GeoPackage** - an OGC standard that is itself a SQLite
file and stores a true geometry type (so it satisfies the "SQLite, geometry as
geometry type" requirement). The resulting `changes.gpkg` can be opened with
the `sqlite3` CLI, QGIS, GeoPandas/Fiona or any SpatiaLite-aware tool.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import rasterio
from rasterio import features
from shapely.geometry import shape

from config import (
    CHANGE_BINARY_PATH,
    CHANGE_MAP_PATH,
    CHANGE_TABLE,
    DATE_AFTER,
    DATE_BEFORE,
    GPKG_PATH,
    MIN_POLYGON_AREA_M2,
)


def _fmt_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def extract_features() -> gpd.GeoDataFrame:
    print("PART 3 - vectorising change polygons and writing the database")

    with rasterio.open(CHANGE_BINARY_PATH) as src:
        binary = src.read(1)
        transform = src.transform
        crs = src.crs
    with rasterio.open(CHANGE_MAP_PATH) as src:
        intensity = src.read(1)

    # Polygonise the "change" class (value == 1).
    mask = binary == 1
    records = []
    for geom, value in features.shapes(binary, mask=mask, transform=transform):
        if value != 1:
            continue
        poly = shape(geom)
        if poly.area < MIN_POLYGON_AREA_M2:  # CRS is metric (UTM) -> area in m^2
            continue
        records.append(poly)

    print(f"  Raw change polygons kept (>= {MIN_POLYGON_AREA_M2:.0f} m^2): {len(records)}")

    # Confidence per polygon = mean change intensity (0-1) of its pixels.
    confidences = _zonal_mean(records, intensity, transform)

    gdf = gpd.GeoDataFrame(
        {
            "date_before": _fmt_date(DATE_BEFORE),
            "date_after": _fmt_date(DATE_AFTER),
            "area_m2": [round(p.area, 1) for p in records],
            "confidence": np.round(confidences, 4),
            "geometry": records,
        },
        crs=crs,
    )
    gdf.insert(0, "id", range(1, len(gdf) + 1))
    gdf = gdf.sort_values("area_m2", ascending=False).reset_index(drop=True)

    GPKG_PATH.unlink(missing_ok=True)
    gdf.to_file(GPKG_PATH, layer=CHANGE_TABLE, driver="GPKG")

    total_ha = gdf["area_m2"].sum() / 10_000
    print(f"  Stored {len(gdf)} features in {GPKG_PATH.name} (layer '{CHANGE_TABLE}')")
    print(f"  Total changed area: {total_ha:.1f} ha\n")
    return gdf


def _zonal_mean(polygons, intensity, transform):
    """Mean raster value inside each polygon, computed via a rasterised mask."""
    out = np.zeros(len(polygons), dtype=np.float32)
    for i, poly in enumerate(polygons):
        m = features.rasterize(
            [(poly, 1)], out_shape=intensity.shape, transform=transform, dtype="uint8"
        ).astype(bool)
        vals = intensity[m]
        out[i] = float(vals.mean()) if vals.size else 0.0
    return out


if __name__ == "__main__":
    extract_features()
