<script lang="ts">
  import MapLibreMap from '$lib/map/MapLibreMap.svelte';
  import { wayneLayerIds } from '@wayne/map';

  // Display order + label + indicator color for each layer. Colors are
  // representative swatches drawn from the layer paint, not exact paint
  // expressions — they're hints, not legends.
  const LAYERS: ReadonlyArray<{ id: string; label: string; swatch: string }> = [
    { id: 'wayne-plants', label: 'plants', swatch: '#b97a4d' },
    { id: 'wayne-substations', label: 'substations', swatch: '#f3ede0' },
    { id: 'wayne-transmission-lines', label: 'transmission', swatch: '#a8703f' },
    { id: 'wayne-gas-pipelines', label: 'gas pipelines', swatch: '#6b5d4a' }
  ];

  let visible = $state(new Set<string>(wayneLayerIds));

  function toggle(id: string) {
    const next = new Set(visible);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    visible = next;
  }
</script>

<svelte:head>
  <title>Map · Wayne</title>
</svelte:head>

<div class="map-shell">
  <MapLibreMap visibleLayers={visible} />

  <aside class="panel" aria-label="Layer controls">
    <h2>Layers</h2>
    <ul>
      {#each LAYERS as layer}
        <li>
          <label>
            <input
              type="checkbox"
              checked={visible.has(layer.id)}
              onchange={() => toggle(layer.id)}
            />
            <span class="swatch" style="background: {layer.swatch}" aria-hidden="true"></span>
            {layer.label}
          </label>
        </li>
      {/each}
    </ul>
  </aside>
</div>

<style>
  :global(html),
  :global(body) {
    height: 100%;
    overflow: hidden;
  }

  .map-shell {
    position: fixed;
    inset: 0;
  }

  .panel {
    position: absolute;
    top: 16px;
    left: 16px;
    z-index: 10;
    background: rgba(243, 237, 224, 0.94);
    border: 1px solid #6b5d4a;
    border-radius: 6px;
    padding: 10px 12px 8px;
    min-width: 180px;
    color: #1c1812;
    font:
      0.85rem / 1.4 'Inter',
      system-ui,
      sans-serif;
    box-shadow: 0 4px 14px rgba(28, 24, 18, 0.1);
    backdrop-filter: blur(4px);
  }

  .panel h2 {
    margin: 0 0 8px;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #6b5d4a;
  }

  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  li {
    padding: 2px 0;
  }

  label {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    user-select: none;
  }

  label:hover {
    color: #3b3228;
  }

  input[type='checkbox'] {
    accent-color: #6f8a52;
    cursor: pointer;
  }

  .swatch {
    width: 12px;
    height: 12px;
    border-radius: 3px;
    border: 1px solid rgba(28, 24, 18, 0.18);
    flex-shrink: 0;
  }
</style>
