<script lang="ts">
  import { BRAND } from '@wayne/ui/brand';

  const { children } = $props();
</script>

<svelte:head>
  <title>{BRAND.productName ?? BRAND.internal}</title>
</svelte:head>

<div class="shell">
  {@render children()}
</div>

<style>
  :global(html, body) {
    margin: 0;
    padding: 0;
    background: #f3eee5;
    color: #1c1812;
    font-family:
      'Inter',
      system-ui,
      -apple-system,
      sans-serif;
    font-size: 0.95rem;
  }

  .shell {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }
</style>
