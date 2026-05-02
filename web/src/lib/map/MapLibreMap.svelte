<script lang="ts">
  import 'maplibre-gl/dist/maplibre-gl.css';
  import { onDestroy, onMount } from 'svelte';
  import { baseStyle } from '@wayne/map';
  import type { Map as MapInstance } from 'maplibre-gl';

  interface Props {
    center?: [number, number];
    zoom?: number;
  }

  const { center = [-98.5, 39.5], zoom = 4 }: Props = $props();

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
  });

  onDestroy(() => {
    map?.remove();
  });
</script>

<div bind:this={mapContainer} class="map"></div>

<style>
  .map {
    width: 100%;
    height: 100%;
    background: #f3eee5;
  }
</style>
