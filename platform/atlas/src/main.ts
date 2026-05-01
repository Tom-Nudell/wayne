/**
 * Atlas entrypoint. Wires MapLibre + PMTiles, registers the canonical
 * gold_atlas layers, and leaves seams for the deck.gl LMP heatmap and
 * scenario-overlay integrations.
 *
 * Aesthetic: the grid as a living mycelial network — calm earth tones,
 * branching hyphae for transmission, fruiting bodies for plants. Alarm
 * colors are reserved for scenario overlays so they read against the base.
 */
import maplibregl from "maplibre-gl";
import { Protocol } from "pmtiles";

import { PALETTE } from "./theme";

const TILE_BASE = import.meta.env.VITE_TILE_BASE ?? "/tiles";

// Register the pmtiles:// protocol so MapLibre can range-fetch a single .pmtiles file.
const protocol = new Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

const HYPHAE_PAINT: maplibregl.LinePaint = {
  // Voltage maps to a warm earth gradient — moss to heartwood — rather than
  // engineering primaries. Higher voltage = older, woodier hyphae.
  "line-color": [
    "interpolate", ["linear"], ["coalesce", ["get", "voltage_kv"], 0],
    0,   PALETTE.loam500,
    115, PALETTE.hypha115,
    230, PALETTE.hypha230,
    345, PALETTE.hypha345,
    500, PALETTE.hypha500,
    765, PALETTE.hypha765,
  ],
  "line-width": [
    "interpolate", ["exponential", 1.4], ["zoom"],
    3,  0.4,
    8,  1.6,
    12, 3.4,
  ],
  "line-opacity": 0.85,
  "line-cap": "round",
  "line-join": "round",
};

const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
    sources: {
      basemap: {
        type: "raster",
        // Carto Positron — soft, low-contrast neutrals that let the network breathe.
        tiles: ["https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"],
        tileSize: 256,
        attribution:
          "© OpenStreetMap contributors · © CARTO · network data per popover provenance",
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
        // Hyphae: transmission as the branching network of a living mat.
        id: "transmission_lines",
        type: "line",
        source: "transmission_lines",
        "source-layer": "transmission_lines",
        paint: HYPHAE_PAINT,
      },
      {
        // Nodes where hyphae braid: substations as small spore points.
        id: "substations",
        type: "circle",
        source: "substations",
        "source-layer": "substations",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 1.2, 10, 3.6],
          "circle-color": PALETTE.bone,
          "circle-stroke-color": PALETTE.loam900,
          "circle-stroke-width": 0.6,
          "circle-opacity": 0.9,
        },
      },
      {
        // Fruiting bodies: generation plants, sized by capacity, colored by fuel family.
        id: "plants",
        type: "circle",
        source: "plants",
        "source-layer": "plants",
        paint: {
          "circle-radius": [
            "interpolate", ["linear"], ["coalesce", ["get", "capacity_mw"], 0],
            0,    2,
            500,  6,
            2000, 11,
            5000, 16,
          ],
          "circle-color": [
            "match", ["get", "fuel"],
            "solar",       PALETTE.fuelSolar,
            "wind",        PALETTE.fuelWind,
            "natural_gas", PALETTE.fuelGas,
            "coal",        PALETTE.fuelCoal,
            "nuclear",     PALETTE.fuelNuclear,
            "hydro",       PALETTE.fuelHydro,
            PALETTE.fuelOther,
          ],
          "circle-stroke-color": PALETTE.loam900,
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
    new maplibregl.Popup({ className: "myc-popup" })
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

// Phase 5+ seams. The data helpers are wired; the visual layers attach here
// once the market mart carries real rows (GridStatus ingest + dbt build).
// Keeping this as a real import (not a comment) forces the types to stay
// in sync with src/data.ts as the mart schema evolves.
import { fetchLmpWindow, fetchQueueSnapshot } from "./data";
void fetchLmpWindow;   // reserved for deck.gl HeatmapLayer
void fetchQueueSnapshot; // reserved for the queue panel

// TODO Phase 5+: ?episode=<id> query string -> fetch overlay GeoJSON; use
//                PALETTE.overload (red) and PALETTE.mitigation (green) — the
//                only saturated colors on the map, so the eye finds them.

export {};
