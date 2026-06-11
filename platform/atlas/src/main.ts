/**
 * Atlas entrypoint. Wires MapLibre + PMTiles, registers the canonical
 * gold_atlas layers, and implements the episode overlay seam.
 *
 * Episode overlay flow:
 *   1. Run: python -m gridagent_orchestrator.run --goal "..." \
 *              --atlas-overlay-dir platform/atlas/public/overlays
 *   2. Open: http://localhost:5173/?episode=<id>
 *   3. Atlas fetches /overlays/<id>/provenance.json → discovers geojson files
 *   4. Each geojson becomes a MapLibre source + layer; provenance panel updates.
 *
 * Aesthetic: the grid as a living mycelial network — calm earth tones,
 * branching hyphae for transmission, fruiting bodies for plants. Alarm
 * colors are reserved for scenario overlays so they read against the base.
 */
import maplibregl from "maplibre-gl";
import { Protocol } from "pmtiles";

import { PALETTE } from "./theme";

const TILE_BASE = import.meta.env.VITE_TILE_BASE ?? "/tiles";
const OVERLAY_BASE = import.meta.env.VITE_OVERLAY_BASE ?? "/overlays";

// Register the pmtiles:// protocol so MapLibre can range-fetch a single .pmtiles file.
const protocol = new Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const HYPHAE_PAINT: Record<string, any> = {
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

// ---------------------------------------------------------------------------
// Synthetic-data toggle (RTS-GMLC 73-bus test system)
// ---------------------------------------------------------------------------
// Features tagged synthetic=true in the tile properties are real-looking but
// not real US infrastructure. The toggle checkbox reveals/hides them.
// The filter is applied after style load because layers don't exist before that.
const BASE_LAYERS = ["substations", "plants", "transmission_lines"] as const;

function applySyntheticFilter(show: boolean): void {
  for (const layer of BASE_LAYERS) {
    if (!map.getLayer(layer)) continue;
    // null = no filter (show all); the expression hides synthetic=true features.
    map.setFilter(layer, show ? null : ["!=", ["get", "synthetic"], true]);
  }
}

map.on("load", () => {
  const cb = document.getElementById("show-synthetic") as HTMLInputElement | null;
  if (cb) {
    // Start with the initial checked state (true = show synthetic).
    applySyntheticFilter(cb.checked);
    cb.addEventListener("change", () => applySyntheticFilter(cb.checked));
  }
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

// ---------------------------------------------------------------------------
// Episode overlay seam  (?episode=<id>)
// ---------------------------------------------------------------------------

interface Provenance {
  episode_id: string;
  question: string;
  started_at: string;
  tools_called: string[];
  overlays: string[];  // list of .geojson filenames in this episode dir
  data_version: string;
  model: string;
}

const panel = document.getElementById("panel")!;

function setPanel(html: string): void {
  panel.innerHTML = html;
}

function escHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function loadEpisodeOverlay(episodeId: string): Promise<void> {
  setPanel(`<strong>loading episode</strong><br/><code>${escHtml(episodeId)}</code>…`);

  let provenance: Provenance;
  try {
    const res = await fetch(`${OVERLAY_BASE}/${episodeId}/provenance.json`);
    if (!res.ok) throw new Error(`provenance fetch ${res.status}`);
    provenance = (await res.json()) as Provenance;
  } catch (err) {
    setPanel(
      `<strong>episode not found</strong><br/>` +
        `<code>${escHtml(episodeId)}</code><br/>` +
        `<small>Run with <code>--atlas-overlay-dir platform/atlas/public/overlays</code> to populate.</small>`,
    );
    console.warn("Episode overlay load failed:", err);
    return;
  }

  // Collect all feature coordinates across overlays for auto-zoom.
  let minLon = Infinity, minLat = Infinity, maxLon = -Infinity, maxLat = -Infinity;
  function expandBounds(coords: number[][]): void {
    for (const pt of coords) {
      const lon = pt[0], lat = pt[1];
      if (lon == null || lat == null) continue;
      if (lon < minLon) minLon = lon;
      if (lat < minLat) minLat = lat;
      if (lon > maxLon) maxLon = lon;
      if (lat > maxLat) maxLat = lat;
    }
  }

  // Load each overlay file listed in provenance.
  let totalFeatures = 0;
  for (const filename of provenance.overlays) {
    const layerId = `ep_${episodeId}_${filename.replace(".geojson", "")}`;
    try {
      const res = await fetch(`${OVERLAY_BASE}/${episodeId}/${filename}`);
      if (!res.ok) continue;
      const geojson = await res.json();
      totalFeatures += (geojson.features as unknown[]).length;

      // Accumulate bounds from all geometries.
      for (const feature of geojson.features as Array<{ geometry: { type: string; coordinates: unknown } }>) {
        const { type, coordinates } = feature.geometry;
        if (type === "LineString") expandBounds(coordinates as number[][]);
        else if (type === "Point") expandBounds([coordinates as number[]]);
        else if (type === "MultiLineString") for (const seg of coordinates as number[][][]) expandBounds(seg);
      }

      map.addSource(layerId, { type: "geojson", data: geojson });

      // N-1 overloads: lines colored by loading percentage.
      if (filename.includes("n1_contingency")) {
        map.addLayer({
          id: layerId,
          type: "line",
          source: layerId,
          layout: {
            "line-cap": "round",
            "line-join": "round",
          },
          paint: {
            "line-color": PALETTE.overload,
            // Width scales with loading: 100% → 2px, 200%+ → 8px.
            "line-width": [
              "interpolate",
              ["linear"],
              ["coalesce", ["get", "loading_pct"], 100],
              100, 2,
              200, 8,
            ],
            "line-opacity": 0.9,
          },
        });
        // Popover on click.
        map.on("click", layerId, (e) => {
          const f = e.features?.[0];
          if (!f) return;
          const p = f.properties ?? {};
          new maplibregl.Popup({ className: "myc-popup", maxWidth: "280px" })
            .setLngLat(e.lngLat)
            .setHTML(
              `<strong>overload: ${escHtml(String(p["monitored"] ?? ""))}</strong><br/>` +
                `<small>outage: ${escHtml(String(p["outage"] ?? ""))}</small><br/>` +
                `<small>loading: ${typeof p["loading_pct"] === "number" ? p["loading_pct"].toFixed(1) : "?"}%</small><br/>` +
                `<small>post flow: ${typeof p["post_flow_mw"] === "number" ? p["post_flow_mw"].toFixed(1) : "?"} MW</small>`,
            )
            .addTo(map);
        });
        map.on("mouseenter", layerId, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", layerId, () => { map.getCanvas().style.cursor = ""; });
      } else {
        // Generic overlay: circle layer for point/polygon data.
        map.addLayer({
          id: layerId,
          type: "circle",
          source: layerId,
          paint: {
            "circle-radius": 5,
            "circle-color": PALETTE.mitigation,
            "circle-opacity": 0.8,
          },
        });
      }
    } catch (err) {
      console.warn(`Failed to load overlay ${filename}:`, err);
    }
  }

  // Fly to the bounding box of all overlay features.
  if (isFinite(minLon) && totalFeatures > 0) {
    // Pad the bounds slightly so lines aren't at the canvas edge.
    const pad = 0.5;
    map.fitBounds(
      [[minLon - pad, minLat - pad], [maxLon + pad, maxLat + pad]],
      { padding: 60, duration: 1200 }
    );
  }

  // Render provenance panel.
  const ts = provenance.started_at
    ? new Date(parseFloat(provenance.started_at) * 1000).toLocaleString()
    : "unknown";
  const toolList = provenance.tools_called
    .filter((t, i, a) => a.indexOf(t) === i)  // dedupe
    .map((t) => `<code>${escHtml(t)}</code>`)
    .join(", ");

  setPanel(
    `<strong>episode · ${escHtml(provenance.episode_id)}</strong><br/>` +
      `<em>${escHtml(provenance.question)}</em><br/><br/>` +
      `<small>run: ${escHtml(ts)}</small><br/>` +
      `<small>model: ${escHtml(provenance.model || "unknown")}</small><br/>` +
      `<small>tools: ${toolList || "none"}</small><br/>` +
      `<small>overlays: ${totalFeatures} features</small>`,
  );
}

// Parse ?episode=<id> and trigger load after the map style is ready.
const episodeId = new URLSearchParams(window.location.search).get("episode");
if (episodeId) {
  map.on("load", () => {
    loadEpisodeOverlay(episodeId).catch(console.error);
  });
} else {
  // Default panel — no episode param.
  setPanel(
    `<strong>gridagent · atlas</strong><br/>` +
      `<em>a living network</em><br/>` +
      `Layers stream from <code>VITE_TILE_BASE</code>; queries run in-browser via DuckDB-WASM.`,
  );
}

// Phase 5+ seams. The data helpers are wired; the visual layers attach here
// once the market mart carries real rows (GridStatus ingest + dbt build).
// Keeping this as a real import (not a comment) forces the types to stay
// in sync with src/data.ts as the mart schema evolves.
import { fetchLmpWindow, fetchQueueSnapshot } from "./data";
void fetchLmpWindow;   // reserved for deck.gl HeatmapLayer
void fetchQueueSnapshot; // reserved for the queue panel

export {};
