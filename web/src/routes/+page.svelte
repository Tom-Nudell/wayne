<script lang="ts">
  import { BRAND } from '@wayne/ui/brand';
  import { PALETTE } from '@wayne/map/palette';
</script>

<main>
  <h1>{BRAND.productName ?? BRAND.internal}</h1>
  <p class="tag">A living network of US energy infrastructure.</p>
  <p class="placeholder">
    This is the marketing landing scaffold. The map ships in Phase 1; auth + Pro
    in Phase 2; launch in Phase 3. See <code>grid-map-engineering-brief.md</code>
    at the repo root.
  </p>
  <p>
    <a href="/map" class="cta">Open the map shell →</a>
  </p>
  <div class="palette" aria-hidden="true">
    {#each Object.entries(PALETTE) as [name, hex]}
      <span class="swatch" style="--c: {hex}" title={`${name} ${hex}`}></span>
    {/each}
  </div>
</main>

<style>
  main {
    max-width: 42rem;
    margin: 4rem auto;
    padding: 0 1.5rem;
  }
  h1 {
    font-size: 2.25rem;
    letter-spacing: -0.01em;
    margin: 0 0 0.5rem;
  }
  .tag {
    color: #6f8a52;
    margin: 0 0 2rem;
    font-style: italic;
  }
  .placeholder {
    color: #5a4f3e;
    line-height: 1.6;
  }
  .palette {
    margin-top: 2rem;
    display: flex;
    gap: 4px;
  }
  .swatch {
    width: 28px;
    height: 28px;
    border-radius: 4px;
    background: var(--c);
    border: 1px solid rgba(0, 0, 0, 0.08);
  }
  .cta {
    color: #1c1812;
    text-decoration: none;
    border-bottom: 1px solid currentColor;
  }
  .cta:hover {
    color: #6f8a52;
  }
</style>
