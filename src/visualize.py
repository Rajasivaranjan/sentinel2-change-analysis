"""PART 4 - Visualisation.

Produces two artefacts in `outputs/`:

* `change_overview.png` - a static matplotlib figure: RGB before / after, the
  continuous change-intensity map, and the extracted change polygons on top of
  the AOI.
* `change_map.html` - an interactive Folium map (AOI + change polygons over a
  satellite basemap), coloured by confidence.
"""
from __future__ import annotations

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio

from config import (
    AOI_PATH,
    CHANGE_MAP_PATH,
    CHANGE_TABLE,
    DATE_AFTER,
    DATE_BEFORE,
    GPKG_PATH,
    OUTPUTS_DIR,
    STACK_PATHS,
)


def _rgb(path):
    """Read a B/G/R stack and return a contrast-stretched RGB array (h, w, 3)."""
    with rasterio.open(path) as src:
        blue, green, red = src.read([1, 2, 3]).astype(np.float32)
    rgb = np.dstack([red, green, blue])
    valid = rgb.sum(axis=2) > 0
    out = np.zeros_like(rgb)
    for i in range(3):
        band = rgb[:, :, i]
        lo, hi = np.percentile(band[valid], (2, 98))
        out[:, :, i] = np.clip((band - lo) / (hi - lo), 0, 1)
    return out


def static_overview(gdf: gpd.GeoDataFrame) -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    aoi = gpd.read_file(AOI_PATH).to_crs(gdf.crs)

    with rasterio.open(CHANGE_MAP_PATH) as src:
        intensity = src.read(1)
        extent = rasterio.plot.plotting_extent(src)

    fig, axes = plt.subplots(2, 2, figsize=(14, 13))

    axes[0, 0].imshow(_rgb(STACK_PATHS[DATE_BEFORE]), extent=extent)
    axes[0, 0].set_title(f"Before - {DATE_BEFORE} (RGB)")

    axes[0, 1].imshow(_rgb(STACK_PATHS[DATE_AFTER]), extent=extent)
    axes[0, 1].set_title(f"After - {DATE_AFTER} (RGB)")

    im = axes[1, 0].imshow(
        np.ma.masked_equal(intensity, 0), extent=extent, cmap="inferno", vmin=0, vmax=1
    )
    axes[1, 0].set_title("Change intensity (CVA magnitude)")
    fig.colorbar(im, ax=axes[1, 0], fraction=0.046, pad=0.04)

    axes[1, 1].imshow(_rgb(STACK_PATHS[DATE_AFTER]), extent=extent)
    if len(gdf):
        gdf.plot(ax=axes[1, 1], facecolor="none", edgecolor="cyan", linewidth=0.8)
    axes[1, 1].set_title(f"Detected change polygons (n={len(gdf)})")

    for ax in axes.ravel():
        aoi.boundary.plot(ax=ax, edgecolor="yellow", linewidth=1.2)
        ax.set_xticks([])
        ax.set_yticks([])

    fig.suptitle("Sentinel-2 change analysis - open-pit mine, Zambia", fontsize=15)
    fig.tight_layout()
    out = OUTPUTS_DIR / "change_overview.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {out.relative_to(OUTPUTS_DIR.parent)}")


def interactive_map(gdf: gpd.GeoDataFrame) -> None:
    try:
        import folium
    except ImportError:
        print("  (folium not installed - skipping interactive map)")
        return

    aoi = gpd.read_file(AOI_PATH).to_crs(4326)
    centroid = aoi.geometry.union_all().centroid
    m = folium.Map(location=[centroid.y, centroid.x], zoom_start=13, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Satellite",
    ).add_to(m)

    folium.GeoJson(
        aoi, name="AOI",
        style_function=lambda _: {"color": "yellow", "fill": False, "weight": 2},
    ).add_to(m)

    if len(gdf):
        g = gdf.to_crs(4326)
        cmax = max(g["confidence"].max(), 1e-6)
        folium.GeoJson(
            g,
            name="Change polygons",
            style_function=lambda f: {
                "fillColor": "#ff3300",
                "color": "#ff3300",
                "weight": 1,
                "fillOpacity": float(0.25 + 0.55 * (f["properties"]["confidence"] / cmax)),
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["id", "area_m2", "confidence", "date_before", "date_after"]
            ),
        ).add_to(m)

    folium.LayerControl().add_to(m)
    out = OUTPUTS_DIR / "change_map.html"
    m.save(str(out))
    print(f"  -> {out.relative_to(OUTPUTS_DIR.parent)}")


def visualize() -> None:
    print("PART 4 - visualisation")
    import rasterio.plot  # noqa: F401  (registers plotting_extent)

    gdf = gpd.read_file(GPKG_PATH, layer=CHANGE_TABLE)
    static_overview(gdf)
    interactive_map(gdf)
    print()


if __name__ == "__main__":
    visualize()
