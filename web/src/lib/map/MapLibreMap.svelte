<script lang="ts">
  import 'maplibre-gl/dist/maplibre-gl.css';
  import { onDestroy, onMount } from 'svelte';
  import { baseStyle, wayneLayerIds } from '@wayne/map';
  import type { Map as MapInstance, MapMouseEvent, MapGeoJSONFeature } from 'maplibre-gl';

  interface Props {
    center?: [number, number];
    zoom?: number;
    /** Set of layer ids to render. Layers not in this set are hidden via setLayoutProperty. */
    visibleLayers?: ReadonlySet<string>;
  }

  const { center = [-98.5, 39.5], zoom = 4, visibleLayers }: Props = $props();

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
        new maplibregl.Popup({
          className: 'myc-popup',
          closeButton: true,
          maxWidth: '320px'
        })
          .setLngLat(e.lngLat)
          .setHTML(renderPopover(f.properties ?? {}))
          .addTo(mapInstance);
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

  function renderPopover(props: Record<string, unknown>): string {
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
</style>
