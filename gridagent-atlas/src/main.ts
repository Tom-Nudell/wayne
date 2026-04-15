/**
 * Atlas entrypoint. Wires MapLibre + PMTiles, registers the canonical
 * gold_atlas layers, and leaves seams for the deck.gl LMP heatmap and
 * scenario-overlay integrations.
 */
import maplibregl from "maplibre-gl";
import { Protocol } from "pmtiles";

const TILE_BASE = import.meta.env.VITE_TILE_BASE ?? "/tiles";

// Register the pmtiles:// protocol so MapLibre can range-fetch a single .pmtiles file.
const protocol = new Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

const VOLTAGE_PAINT: maplibregl.LinePaint = {
  "line-color": [
    "interpolate", ["linear"], ["coalesce", ["get", "voltage_kv"], 0],
    0, "#888",
    115, "#3b82f6",
    230, "#10b981",
    345, "#f59e0b",
    500, "#ef4444",
    765, "#a855f7",
  ],
  "line-width": [
    "interpolate", ["linear"], ["zoom"],
    3, 0.5,
    8, 1.5,
    12, 3,
  ],
};

const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    sources: {
      basemap: {
        type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256,
        attribution: "© OpenStreetMap contributors",
      },
      transmission_lines: {
        type: "vector",
        url: `pmtiles://${TILE_BASE}/transmission_lines.pmtiles`,
      },
      substations: {
        type: "vector",
        url: `pmtiles://${TILE_BASE}/substations.pmtiles`,
      },
      plants: {
        type: "vector",
        url: `pmtiles://${TILE_BASE}/plants.pmtiles`,
      },
    },
    layers: [
      { id: "basemap", type: "raster", source: "basemap" },
      {
        id: "transmission_lines",
        type: "line",
        source: "transmission_lines",
        "source-layer": "transmission_lines",
        paint: VOLTAGE_PAINT,
      },
      {
        id: "substations",
        type: "circle",
        source: "substations",
        "source-layer": "substations",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 1.5, 10, 4],
          "circle-color": "#fff",
          "circle-stroke-color": "#000",
          "circle-stroke-width": 0.5,
        },
      },
      {
        id: "plants",
        type: "circle",
        source: "plants",
        "source-layer": "plants",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "capacity_mw"], 0, 2, 2000, 12],
          "circle-color": [
            "match", ["get", "fuel"],
            "solar", "#fbbf24",
            "wind", "#22d3ee",
            "natural_gas", "#f97316",
            "coal", "#1f2937",
            "nuclear", "#a78bfa",
            "hydro", "#3b82f6",
            "#9ca3af",
          ],
          "circle-stroke-color": "#000",
          "circle-stroke-width": 0.5,
          "circle-opacity": 0.85,
        },
      },
    ],
  },
  center: [-98.5, 39.5],
  zoom: 4,
});

// Provenance popovers — every gold_atlas feature carries `sources` and `licenses` arrays.
for (const layer of ["substations", "plants", "transmission_lines"]) {
  map.on("click", layer, (e) => {
    const f = e.features?.[0];
    if (!f) return;
    const sources = (f.properties?.sources as string) ?? "(unknown)";
    const licenses = (f.properties?.licenses as string) ?? "(unknown)";
    new maplibregl.Popup()
      .setLngLat(e.lngLat)
      .setHTML(
        `<strong>${f.properties?.name ?? layer}</strong><br/>` +
          `<small>kind: ${f.properties?.kind ?? layer}</small><br/>` +
          `<small>sources: ${sources}</small><br/>` +
          `<small>licenses: ${licenses}</small>`,
      )
      .addTo(map);
  });
}

// TODO Phase 5+: deck.gl HeatmapLayer over gold_market.lmp_hourly via DuckDB-WASM.
// TODO Phase 5+: ?episode=<id> query string -> fetch overlay GeoJSON, add red/green layers.

export {};
