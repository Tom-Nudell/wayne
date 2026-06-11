<script lang="ts">
  import 'maplibre-gl/dist/maplibre-gl.css';
  import { onDestroy, onMount } from 'svelte';
  import { baseStyle, wayneLayerIds, PALETTE } from '@wayne/map';
  import type { Map as MapInstance, MapMouseEvent, MapGeoJSONFeature } from 'maplibre-gl';
  import type { StudyFeatureRef } from '@wayne/api';

  interface Props {
    center?: [number, number];
    zoom?: number;
    /** Set of layer ids to render. Layers not in this set are hidden via setLayoutProperty. */
    visibleLayers?: ReadonlySet<string>;
    /**
     * Testability track (dev-flagged): when set, popovers grow a
     * "Run N-1 study from here" action that reports the clicked feature.
     */
    onRunStudy?: (feature: StudyFeatureRef) => void;
    /** URL of an episode overlay GeoJSON to draw in alarm colors; null clears it. */
    studyOverlayUrl?: string | null;
  }

  const {
    center = [-98.5, 39.5],
    zoom = 4,
    visibleLayers,
    onRunStudy,
    studyOverlayUrl = null
  }: Props = $props();

  const OVERLAY_SOURCE = 'wayne-study-overlay';
  const OVERLAY_LAYER = 'wayne-study-overload';

  let mapContainer: HTMLDivElement;
  let map: MapInstance | undefined = $state(undefined);

  onMount(async () => {
    // maplibre-gl + pmtiles touch window/document, so we keep them
    // browser-only via dynamic import. Never let them sneak into SSR.
    const maplibreModule = await import('maplibre-gl');
    const pmtilesModule = await import('pmtiles');
    const maplibregl = maplibreModule.default;
    const { Protocol } = pmtilesModule;

    const protocol = new Protocol();
    maplibregl.addProtocol('pmtiles', protocol.tile);

    map = new maplibregl.Map({
      container: mapContainer,
      style: baseStyle,
      center,
      zoom,
      // Default attribution control is on; the source's `attribution`
      // field surfaces here. Phase 1 will replace this with our own
      // control that renders from license.json sidecars per zoom.
      attributionControl: { compact: true }
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), 'top-right');

    // Provenance popovers — every gold_atlas feature carries `sources`
    // and `licenses` arrays. Tippecanoe stringifies arrays in vector
    // tile properties; parseArray() reconstructs them.
    const mapInstance = map;
    for (const id of wayneLayerIds) {
      mapInstance.on('click', id, (e: MapMouseEvent & { features?: MapGeoJSONFeature[] }) => {
        const f = e.features?.[0];
        if (!f) return;
        const props = f.properties ?? {};
        const popup = new maplibregl.Popup({
          className: 'myc-popup',
          closeButton: true,
          maxWidth: '320px'
        })
          .setLngLat(e.lngLat)
          .setHTML(renderPopover(props, Boolean(onRunStudy)))
          .addTo(mapInstance);
        if (onRunStudy) {
          // setHTML can't carry handlers; bind to the rendered button.
          popup
            .getElement()
            ?.querySelector<HTMLButtonElement>('button.run-study')
            ?.addEventListener('click', () => {
              onRunStudy({
                kind: String(props.kind ?? 'feature'),
                feature_id: String(props.feature_id ?? props.name ?? 'unknown'),
                name: props.name != null ? String(props.name) : undefined,
                lng: e.lngLat.lng,
                lat: e.lngLat.lat
              });
              popup.remove();
            });
        }
      });
      mapInstance.on('mouseenter', id, () => {
        mapInstance.getCanvas().style.cursor = 'pointer';
      });
      mapInstance.on('mouseleave', id, () => {
        mapInstance.getCanvas().style.cursor = '';
      });
    }
  });

  onDestroy(() => {
    map?.remove();
  });

  // React to visibleLayers changes by toggling MapLibre layout visibility.
  // Tiles stay loaded — only the render is hidden — so toggles are cheap.
  $effect(() => {
    const m = map;
    const visible = visibleLayers;
    if (!m || !visible) return;
    for (const id of wayneLayerIds) {
      try {
        m.setLayoutProperty(id, 'visibility', visible.has(id) ? 'visible' : 'none');
      } catch {
        // Layer may not be ready yet on first render; safe to ignore.
      }
    }
  });

  // Study overlay: agent-discovered N-1 overloads as a GeoJSON line layer.
  // PALETTE.overload is one of the two reserved alarm colors — the only
  // saturated hues on the map, so the eye finds the result immediately.
  $effect(() => {
    const m = map;
    const url = studyOverlayUrl;
    if (!m) return;
    const apply = () => {
      if (m.getLayer(OVERLAY_LAYER)) m.removeLayer(OVERLAY_LAYER);
      if (m.getSource(OVERLAY_SOURCE)) m.removeSource(OVERLAY_SOURCE);
      if (!url) return;
      m.addSource(OVERLAY_SOURCE, { type: 'geojson', data: url });
      m.addLayer({
        id: OVERLAY_LAYER,
        type: 'line',
        source: OVERLAY_SOURCE,
        paint: {
          'line-color': PALETTE.overload,
          // Worse overloads draw heavier: 100% loading → 2px, 300% → 6px.
          'line-width': [
            'interpolate',
            ['linear'],
            ['coalesce', ['get', 'loading_pct'], 100],
            100,
            2,
            300,
            6
          ],
          'line-opacity': 0.9
        }
      });
    };
    // Don't gate on isStyleLoaded(): it reports false whenever any tile is
    // still loading, and the 'load' event only ever fires once per map — a
    // listener added after that waits forever. addSource works any time
    // after initial style load, so try immediately and fall back to the
    // next 'idle' (which re-fires) only if the style genuinely isn't ready.
    try {
      apply();
    } catch {
      m.once('idle', () => {
        try {
          apply();
        } catch {
          // Style never became ready; nothing to draw.
        }
      });
    }
  });

  // ---- popover rendering helpers ----

  function escapeHtml(s: string): string {
    return s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function fmtNumber(n: unknown, unit: string): string {
    if (typeof n !== 'number' || !Number.isFinite(n)) return '';
    return `${n.toLocaleString(undefined, { maximumFractionDigits: 1 })} ${unit}`;
  }

  function parseArray(v: unknown): string[] {
    if (Array.isArray(v)) return v.map(String);
    if (typeof v === 'string') {
      try {
        const parsed = JSON.parse(v);
        if (Array.isArray(parsed)) return parsed.map(String);
      } catch {
        // not JSON — treat as a single string entry
      }
      return [v];
    }
    return [];
  }

  function renderPopover(props: Record<string, unknown>, withStudyAction = false): string {
    const kind = String(props.kind ?? 'feature');
    const name = String(props.name ?? props.feature_id ?? kind);
    const lines: string[] = [
      `<strong>${escapeHtml(name)}</strong>`,
      `<small class="kind">${escapeHtml(kind.replace(/_/g, ' '))}</small>`
    ];
    if (props.voltage_kv != null) {
      lines.push(`<div>voltage: ${fmtNumber(props.voltage_kv, 'kV')}</div>`);
    }
    if (props.capacity_mw != null) {
      lines.push(`<div>capacity: ${fmtNumber(props.capacity_mw, 'MW')}</div>`);
    }
    if (props.fuel != null) {
      lines.push(`<div>fuel: ${escapeHtml(String(props.fuel))}</div>`);
    }
    if (props.operator != null) {
      lines.push(`<div>operator: ${escapeHtml(String(props.operator))}</div>`);
    }
    if (props.state != null) {
      lines.push(`<div>state: ${escapeHtml(String(props.state))}</div>`);
    }
    const sources = parseArray(props.sources);
    const licenses = parseArray(props.licenses);
    if (sources.length || licenses.length) {
      const parts: string[] = [];
      if (sources.length) parts.push(`sources: ${sources.map(escapeHtml).join(', ')}`);
      if (licenses.length) parts.push(`licenses: ${licenses.map(escapeHtml).join(', ')}`);
      lines.push(`<div class="prov">${parts.join(' · ')}</div>`);
    }
    if (withStudyAction) {
      lines.push(`<button type="button" class="run-study">Run N-1 study from here</button>`);
    }
    return lines.join('');
  }
</script>

<div bind:this={mapContainer} class="map"></div>

<style>
  .map {
    width: 100%;
    height: 100%;
    background: #f3eee5;
  }

  /* Mycelium-themed MapLibre popup. */
  :global(.myc-popup .maplibregl-popup-content) {
    background: #f3ede0;
    color: #1c1812;
    border: 1px solid #6b5d4a;
    box-shadow: 0 6px 20px rgba(28, 24, 18, 0.12);
    padding: 12px 14px;
    font:
      0.85rem / 1.45 'Inter',
      system-ui,
      sans-serif;
  }
  :global(.myc-popup .maplibregl-popup-content strong) {
    display: block;
    font-size: 0.95rem;
    margin-bottom: 2px;
  }
  :global(.myc-popup .kind) {
    color: #6b5d4a;
    text-transform: lowercase;
    letter-spacing: 0.04em;
    font-size: 0.7rem;
  }
  :global(.myc-popup .prov) {
    margin-top: 6px;
    padding-top: 6px;
    border-top: 1px solid rgba(28, 24, 18, 0.12);
    font-size: 0.7rem;
    color: #6b5d4a;
  }
  :global(.myc-popup .maplibregl-popup-tip) {
    border-top-color: #6b5d4a !important;
  }
  :global(.myc-popup button.run-study) {
    margin-top: 8px;
    width: 100%;
    padding: 5px 8px;
    background: #6f8a52;
    color: #f3ede0;
    border: none;
    border-radius: 4px;
    font:
      600 0.75rem 'Inter',
      system-ui,
      sans-serif;
    cursor: pointer;
  }
  :global(.myc-popup button.run-study:hover) {
    background: #5d7544;
  }
</style>
