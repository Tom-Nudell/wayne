<script lang="ts">
  import MapLibreMap from '$lib/map/MapLibreMap.svelte';
</script>

<svelte:head>
  <title>Map · Wayne</title>
</svelte:head>

<div class="map-shell">
  <MapLibreMap />
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
</style>
