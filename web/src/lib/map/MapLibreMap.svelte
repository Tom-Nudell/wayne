<script lang="ts">
  import 'maplibre-gl/dist/maplibre-gl.css';
  import { onDestroy, onMount } from 'svelte';
  import { baseStyle, wayneLayerIds, PALETTE } from '@wayne/map';
  import type {
    Map as MapInstance,
    MapMouseEvent,
    MapGeoJSONFeature,
    GeoJSONSource
  } from 'maplibre-gl';
  import type { StudyFeatureRef, StudyKind } from '@wayne/api';
  import type { FeatureCollection } from 'geojson';

  interface Props {
    center?: [number, number];
    zoom?: number;
    /** Set of layer ids to render. Layers not in this set are hidden via setLayoutProperty. */
    visibleLayers?: ReadonlySet<string>;
    /**
     * Testability track (dev-flagged): when set, popovers grow study
     * actions (N-1, price map) that report the clicked feature.
     */
    onRunStudy?: (feature: StudyFeatureRef, study: StudyKind) => void;
    /** URL of an episode overlay GeoJSON to draw in alarm colors; null clears it. */
    studyOverlayUrl?: string | null;
    /**
     * DC OPF price surface: kind:"lmp" bus Points + kind:"binding" lines.
     * Passed as a FeatureCollection (not a URL) so live what-if solves can
     * update prices in place via setData. Null clears the layer.
     */
    lmpOverlay?: FeatureCollection | null;
    /** Color ramp domain for the LMP layer, $/MWh. */
    lmpDomain?: { min: number; max: number } | null;
    /** Reports clicks on LMP bus points (for the what-if slider). */
    onSelectLmpBus?: (busId: string, lmp: number) => void;
    /** ADER / beneficiary POI / active constraint features for the transfer demo. */
    beneficiaryOverlay?: FeatureCollection | null;
    /** Reports clicks on beneficiary POI points. */
    onSelectBeneficiaryPoi?: (busId: string) => void;
    /** A stable run id; changing it fits the map to the demo study once. */
    beneficiaryStudyKey?: string | null;
  }

  const {
    center = [-98.5, 39.5],
    zoom = 4,
    visibleLayers,
    onRunStudy,
    studyOverlayUrl = null,
    lmpOverlay = null,
    lmpDomain = null,
    onSelectLmpBus,
    beneficiaryOverlay = null,
    onSelectBeneficiaryPoi,
    beneficiaryStudyKey = null
  }: Props = $props();

  const OVERLAY_SOURCE = 'wayne-study-overlay';
  const OVERLAY_LAYER = 'wayne-study-overload';
  const LMP_SOURCE = 'wayne-lmp-overlay';
  const LMP_POINT_LAYER = 'wayne-lmp-points';
  const LMP_BINDING_LAYER = 'wayne-lmp-binding';
  const BENEFICIARY_SOURCE = 'wayne-beneficiary-load';
  const BENEFICIARY_OUTAGE_LAYER = 'wayne-beneficiary-outages';
  const BENEFICIARY_CONSTRAINT_LAYER = 'wayne-beneficiary-constraints';
  const BENEFICIARY_ADER_LAYER = 'wayne-beneficiary-ader';
  const BENEFICIARY_POI_LAYER = 'wayne-beneficiary-pois';

  // Sequential price ramp: cool teal (cheap) → parchment → alarm red
  // (expensive). Saturated colors are reserved for overlays, which this is.
  // The legend gradient in map/+page.svelte mirrors these stops.
  const LMP_RAMP: [string, string, string] = ['#2c6e6a', '#e8c76f', '#c0392b'];

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
          // setHTML can't carry handlers; bind to the rendered buttons.
          const featureRef = (): StudyFeatureRef => ({
            kind: String(props.kind ?? 'feature'),
            feature_id: String(props.feature_id ?? props.name ?? 'unknown'),
            name: props.name != null ? String(props.name) : undefined,
            lng: e.lngLat.lng,
            lat: e.lngLat.lat
          });
          const el = popup.getElement();
          el?.querySelector<HTMLButtonElement>('button.run-study')?.addEventListener(
            'click',
            () => {
              onRunStudy(featureRef(), 'n1_contingency');
              popup.remove();
            }
          );
          el?.querySelector<HTMLButtonElement>('button.run-price')?.addEventListener(
            'click',
            () => {
              onRunStudy(featureRef(), 'dc_opf');
              popup.remove();
            }
          );
        }
      });
      mapInstance.on('mouseenter', id, () => {
        mapInstance.getCanvas().style.cursor = 'pointer';
      });
      mapInstance.on('mouseleave', id, () => {
        mapInstance.getCanvas().style.cursor = '';
      });
    }

    // LMP bus points feed the what-if slider on click.
    mapInstance.on(
      'click',
      LMP_POINT_LAYER,
      (e: MapMouseEvent & { features?: MapGeoJSONFeature[] }) => {
        const f = e.features?.[0];
        if (!f || !onSelectLmpBus) return;
        const props = f.properties ?? {};
        onSelectLmpBus(String(props.bus_id ?? ''), Number(props.lmp_usd_per_mwh ?? 0));
      }
    );
    mapInstance.on('mouseenter', LMP_POINT_LAYER, () => {
      mapInstance.getCanvas().style.cursor = 'pointer';
    });
    mapInstance.on('mouseleave', LMP_POINT_LAYER, () => {
      mapInstance.getCanvas().style.cursor = '';
    });

    // Beneficiary POIs are the map-side selector for the transfer slider.
    mapInstance.on(
      'click',
      BENEFICIARY_POI_LAYER,
      (e: MapMouseEvent & { features?: MapGeoJSONFeature[] }) => {
        const f = e.features?.[0];
        if (!f || !onSelectBeneficiaryPoi) return;
        onSelectBeneficiaryPoi(String(f.properties?.bus_id ?? ''));
      }
    );
    mapInstance.on('mouseenter', BENEFICIARY_POI_LAYER, () => {
      mapInstance.getCanvas().style.cursor = 'pointer';
    });
    mapInstance.on('mouseleave', BENEFICIARY_POI_LAYER, () => {
      mapInstance.getCanvas().style.cursor = '';
    });
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

  // Beneficiary-load demo. Only the selected POI's limiting monitored and
  // outage branches are included in the collection, so a slider update is a
  // cheap setData() and cannot be mistaken for a physical ADER-to-POI path.
  $effect(() => {
    const m = map;
    const collection = beneficiaryOverlay;
    if (!m) return;
    const remove = () => {
      if (m.getLayer(BENEFICIARY_POI_LAYER)) m.removeLayer(BENEFICIARY_POI_LAYER);
      if (m.getLayer(BENEFICIARY_ADER_LAYER)) m.removeLayer(BENEFICIARY_ADER_LAYER);
      if (m.getLayer(BENEFICIARY_CONSTRAINT_LAYER)) {
        m.removeLayer(BENEFICIARY_CONSTRAINT_LAYER);
      }
      if (m.getLayer(BENEFICIARY_OUTAGE_LAYER)) m.removeLayer(BENEFICIARY_OUTAGE_LAYER);
      if (m.getSource(BENEFICIARY_SOURCE)) m.removeSource(BENEFICIARY_SOURCE);
    };
    const apply = () => {
      if (!collection) {
        remove();
        return;
      }
      const existing = m.getSource(BENEFICIARY_SOURCE) as GeoJSONSource | undefined;
      if (existing) {
        existing.setData(collection);
        return;
      }
      m.addSource(BENEFICIARY_SOURCE, { type: 'geojson', data: collection });
      m.addLayer({
        id: BENEFICIARY_OUTAGE_LAYER,
        type: 'line',
        source: BENEFICIARY_SOURCE,
        filter: ['==', ['get', 'kind'], 'beneficiary-outage'],
        paint: {
          'line-color': PALETTE.heartwood,
          'line-width': 2,
          'line-dasharray': [1.5, 1.5],
          'line-opacity': 0.65
        }
      });
      m.addLayer({
        id: BENEFICIARY_CONSTRAINT_LAYER,
        type: 'line',
        source: BENEFICIARY_SOURCE,
        filter: ['==', ['get', 'kind'], 'beneficiary-constraint'],
        paint: {
          'line-color': [
            'case',
            ['>', ['get', 'projected_loading_pct'], 100],
            PALETTE.overload,
            PALETTE.mitigation
          ],
          'line-width': ['interpolate', ['linear'], ['get', 'rank'], 1, 5, 4, 2.5],
          'line-opacity': 0.92
        }
      });
      m.addLayer({
        id: BENEFICIARY_ADER_LAYER,
        type: 'circle',
        source: BENEFICIARY_SOURCE,
        filter: ['==', ['get', 'kind'], 'ader'],
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 5, 9, 9],
          'circle-color': [
            'case',
            ['>=', ['get', 'dispatch_mw'], 0],
            PALETTE.moss,
            PALETTE.heartwood
          ],
          'circle-stroke-color': PALETTE.paper,
          'circle-stroke-width': 2,
          'circle-opacity': 0.95
        }
      });
      m.addLayer({
        id: BENEFICIARY_POI_LAYER,
        type: 'circle',
        source: BENEFICIARY_SOURCE,
        filter: ['==', ['get', 'kind'], 'beneficiary-poi'],
        paint: {
          'circle-radius': [
            'interpolate',
            ['linear'],
            ['get', 'unlocked_capacity_mw'],
            0,
            6,
            180,
            13
          ],
          'circle-color': [
            'case',
            ['==', ['get', 'selected'], true],
            PALETTE.paper,
            PALETTE.mitigation
          ],
          'circle-stroke-color': [
            'case',
            ['==', ['get', 'selected'], true],
            PALETTE.mitigation,
            PALETTE.loam900
          ],
          'circle-stroke-width': ['case', ['==', ['get', 'selected'], true], 4, 1.2],
          'circle-opacity': 0.96
        }
      });
    };
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

  let lastBeneficiaryStudyKey: string | null = null;
  $effect(() => {
    const m = map;
    const key = beneficiaryStudyKey;
    const collection = beneficiaryOverlay;
    if (!m || !key || !collection || key === lastBeneficiaryStudyKey) return;
    const coordinates: [number, number][] = [];
    for (const feature of collection.features) {
      if (feature.geometry?.type === 'Point') {
        coordinates.push(feature.geometry.coordinates as [number, number]);
      } else if (feature.geometry?.type === 'LineString') {
        coordinates.push(...(feature.geometry.coordinates as [number, number][]));
      }
    }
    if (!coordinates.length) return;
    lastBeneficiaryStudyKey = key;
    const longitudes = coordinates.map(([longitude]) => longitude);
    const latitudes = coordinates.map(([, latitude]) => latitude);
    const compact = window.innerWidth < 700;
    m.fitBounds(
      [
        [Math.min(...longitudes), Math.min(...latitudes)],
        [Math.max(...longitudes), Math.max(...latitudes)]
      ],
      {
        padding: compact
          ? { top: 70, right: 35, bottom: 260, left: 35 }
          : { top: 65, right: 430, bottom: 65, left: 245 },
        maxZoom: 8,
        duration: 900
      }
    );
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

  // DC OPF price surface: bus circles colored by LMP + binding branches as
  // dashed alarm lines underneath. The source holds a FeatureCollection so
  // live what-if solves can setData without tearing layers down.
  $effect(() => {
    const m = map;
    const collection = lmpOverlay;
    const domain = lmpDomain;
    if (!m) return;
    const apply = () => {
      if (!collection) {
        if (m.getLayer(LMP_POINT_LAYER)) m.removeLayer(LMP_POINT_LAYER);
        if (m.getLayer(LMP_BINDING_LAYER)) m.removeLayer(LMP_BINDING_LAYER);
        if (m.getSource(LMP_SOURCE)) m.removeSource(LMP_SOURCE);
        return;
      }
      const existing = m.getSource(LMP_SOURCE) as GeoJSONSource | undefined;
      if (existing) {
        existing.setData(collection);
      } else {
        m.addSource(LMP_SOURCE, { type: 'geojson', data: collection });
      }
      // (Re)build the point layer so a changed domain re-ranges the ramp.
      if (m.getLayer(LMP_POINT_LAYER)) m.removeLayer(LMP_POINT_LAYER);
      if (m.getLayer(LMP_BINDING_LAYER)) m.removeLayer(LMP_BINDING_LAYER);
      const lo = domain?.min ?? 0;
      const hi = domain?.max ?? Math.max(lo + 1, 1);
      const mid = (lo + hi) / 2;
      m.addLayer({
        id: LMP_BINDING_LAYER,
        type: 'line',
        source: LMP_SOURCE,
        filter: ['==', ['get', 'kind'], 'binding'],
        paint: {
          'line-color': PALETTE.overload,
          'line-width': 2.5,
          'line-dasharray': [2, 1.5],
          'line-opacity': 0.9
        }
      });
      m.addLayer({
        id: LMP_POINT_LAYER,
        type: 'circle',
        source: LMP_SOURCE,
        filter: ['==', ['get', 'kind'], 'lmp'],
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 3.5, 10, 8],
          'circle-color': [
            'interpolate',
            ['linear'],
            ['get', 'lmp_usd_per_mwh'],
            lo,
            LMP_RAMP[0],
            mid,
            LMP_RAMP[1],
            hi,
            LMP_RAMP[2]
          ],
          'circle-stroke-color': PALETTE.loam900,
          'circle-stroke-width': 0.8,
          'circle-opacity': 0.95
        }
      });
    };
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
      const synthetic = props.synthetic === true || props.synthetic === 'true';
      if (synthetic) {
        // Mirrors the server-side gate in /api/study: synthetic features
        // have no real data backing, so studies never launch from them.
        lines.push(
          `<div class="no-study">synthetic feature — no data backing, studies disabled</div>`
        );
      } else {
        lines.push(`<button type="button" class="run-study">Run N-1 study from here</button>`);
        lines.push(`<button type="button" class="run-price">Price map from here</button>`);
      }
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
  :global(.myc-popup button.run-price) {
    margin-top: 6px;
    width: 100%;
    padding: 5px 8px;
    background: #2c6e6a;
    color: #f3ede0;
    border: none;
    border-radius: 4px;
    font:
      600 0.75rem 'Inter',
      system-ui,
      sans-serif;
    cursor: pointer;
  }
  :global(.myc-popup button.run-price:hover) {
    background: #235955;
  }
  :global(.myc-popup .no-study) {
    margin-top: 8px;
    padding: 5px 8px;
    background: rgba(28, 24, 18, 0.06);
    border-radius: 4px;
    font-size: 0.7rem;
    color: #6b5d4a;
    font-style: italic;
  }
</style>
