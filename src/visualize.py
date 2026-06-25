"""PART 4 - Visualisation.

Produces two artefacts in `outputs/`:

* `change_overview.png` - a static matplotlib figure: RGB before / after, the
  continuous change-intensity map, and the extracted change polygons on top of
  the AOI.
* `change_map.html` - an interactive Folium map with a **before/after swipe**
  (Before RGB on the left pane, After RGB on the right, dragged with a slider),
  the change polygons overlaid on top, and a layer control to toggle the change
  and AOI layers on/off.
"""
from __future__ import annotations

import base64
import io

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.transform import array_bounds, from_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject

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


def _rgb_overlay_4326(path, max_px: int = 1100):
    """Reproject a B/G/R stack to WGS84 and return (data-URI PNG, [[S,W],[N,E]]).

    The image is a contrast-stretched RGBA PNG (nodata -> transparent), ready to
    drop onto a Leaflet map as an ImageOverlay. We reproject to EPSG:4326 so the
    overlay lines up with the slippy-map basemap; over an AOI this small the
    linear lat/lon stretch is negligible.
    """
    dst_crs = "EPSG:4326"
    with rasterio.open(path) as src:
        transform, w, h = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        west, south, east, north = array_bounds(h, w, transform)

        # Cap the resolution so the embedded PNG stays small.
        scale = min(1.0, max_px / max(w, h))
        w, h = max(1, int(w * scale)), max(1, int(h * scale))
        transform = from_bounds(west, south, east, north, w, h)

        bands = np.zeros((3, h, w), dtype=np.float32)
        for i in range(3):  # stack order is Blue, Green, Red
            reproject(
                source=rasterio.band(src, i + 1),
                destination=bands[i],
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=transform,
                dst_crs=dst_crs,
                src_nodata=0,
                dst_nodata=0,
                resampling=Resampling.bilinear,
            )

    red, green, blue = bands[2], bands[1], bands[0]
    rgb = np.dstack([red, green, blue])
    valid = np.all(bands > 0, axis=0)
    rgba = np.zeros((h, w, 4), dtype=np.float32)
    for i in range(3):
        ch = rgb[:, :, i]
        lo, hi = np.percentile(ch[valid], (2, 98))
        rgba[:, :, i] = np.clip((ch - lo) / (hi - lo + 1e-9), 0, 1)
    rgba[:, :, 3] = valid.astype(np.float32)

    buf = io.BytesIO()
    plt.imsave(buf, rgba, format="png")
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return uri, [[south, west], [north, east]]


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

    from folium.plugins import SideBySideLayers

    aoi = gpd.read_file(AOI_PATH).to_crs(4326)
    centroid = aoi.geometry.union_all().centroid
    m = folium.Map(location=[centroid.y, centroid.x], zoom_start=13, tiles=None)

    # Satellite basemap sits underneath everything (revealed outside the AOI).
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Satellite", control=False,
    ).add_to(m)

    # Before (left pane) and After (right pane) RGB overlays, driven by a swipe
    # slider rather than the layer control.
    before_uri, bounds = _rgb_overlay_4326(STACK_PATHS[DATE_BEFORE])
    after_uri, _ = _rgb_overlay_4326(STACK_PATHS[DATE_AFTER])
    before_layer = folium.raster_layers.ImageOverlay(
        before_uri, bounds=bounds, name=f"Before {DATE_BEFORE}", control=False
    ).add_to(m)
    after_layer = folium.raster_layers.ImageOverlay(
        after_uri, bounds=bounds, name=f"After {DATE_AFTER}", control=False
    ).add_to(m)

    # The leaflet-side-by-side plugin calls getContainer() on each layer, which
    # ImageOverlay lacks (it exposes getElement()). Alias it before the control
    # initialises so the swipe works with image overlays.
    from branca.element import MacroElement
    from jinja2 import Template

    patch = MacroElement()
    patch._template = Template(
        "{% macro script(this, kwargs) %}"
        "L.ImageOverlay.prototype.getContainer = L.ImageOverlay.prototype.getElement;"
        "{% endmacro %}"
    )
    patch.add_to(m)

    SideBySideLayers(layer_left=before_layer, layer_right=after_layer).add_to(m)

    # Change polygons overlaid on top (on the After / right side), toggleable.
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

    # AOI outline, toggleable.
    folium.GeoJson(
        aoi, name="AOI",
        style_function=lambda _: {"color": "yellow", "fill": False, "weight": 2},
    ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    # Small legend so the swipe is self-explanatory.
    legend = folium.Element(
        f"""
        <div style="position: fixed; bottom: 20px; left: 20px; z-index: 9999;
                    background: rgba(0,0,0,0.7); color: #fff; padding: 8px 12px;
                    font: 12px sans-serif; border-radius: 6px;">
          <b>Drag the slider</b> &nbsp;|&nbsp;
          Left: Before {DATE_BEFORE} &nbsp; Right: After {DATE_AFTER}<br>
          <span style="color:#ff3300;">&#9632;</span> detected change (toggle at top-right)
        </div>"""
    )
    m.get_root().html.add_child(legend)

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
