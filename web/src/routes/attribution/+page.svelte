<script lang="ts">
  import { BRAND } from '@wayne/ui/brand';
  import type { PageData } from './$types';

  const { data }: { data: PageData } = $props();
</script>

<svelte:head>
  <title>Data Attribution · {BRAND.productName ?? BRAND.internal}</title>
</svelte:head>

<main>
  <h1>Data Attribution</h1>
  <p class="intro">
    Every feature on the map is derived from one or more public data sources. This page lists
    all sources, their licenses, and the attribution required by each license. It is generated
    automatically from the data pipeline — never hand-edited.
  </p>

  {#if !data.dataAvailable}
    <div class="placeholder">
      <p>
        Attribution data not yet generated. Run the data pipeline first:
      </p>
      <pre>gridagent-data bundle</pre>
    </div>
  {:else if data.layers.length === 0}
    <div class="placeholder">
      <p>No license sidecars found. The bundle directory may be empty.</p>
    </div>
  {:else}
    <table>
      <thead>
        <tr>
          <th>Layer</th>
          <th>License</th>
          <th>Attribution</th>
          <th>Features</th>
          <th>Required</th>
        </tr>
      </thead>
      <tbody>
        {#each data.layers as layer}
          {#each layer.licenses as lic, i}
            <tr class:first-row={i === 0}>
              {#if i === 0}
                <td rowspan={layer.licenses.length} class="layer-name">
                  {layer.layer.replace(/_/g, '\u00a0')}
                </td>
              {/if}
              <td>
                <a href={lic.url} target="_blank" rel="noopener noreferrer">{lic.spdx}</a>
              </td>
              <td class="citation">{lic.citation || '—'}</td>
              {#if i === 0}
                <td rowspan={layer.licenses.length} class="feature-count">
                  {layer.feature_count.toLocaleString()}
                </td>
              {/if}
              <td class="required">
                {#if lic.attribution_required}
                  <span class="badge required-yes">Yes</span>
                {:else}
                  <span class="badge required-no">No</span>
                {/if}
              </td>
            </tr>
          {/each}
        {/each}
      </tbody>
    </table>

    <p class="generated">
      Generated {data.layers[0]?.generated_at
        ? new Date(data.layers[0].generated_at).toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'long',
            day: 'numeric'
          })
        : 'unknown date'}.
    </p>
  {/if}
</main>

<style>
  main {
    max-width: 72rem;
    margin: 3rem auto;
    padding: 0 1.5rem;
  }

  h1 {
    font-size: 1.6rem;
    font-weight: 600;
    color: #1c1812;
    margin-bottom: 0.75rem;
  }

  .intro {
    color: #4a3f35;
    max-width: 52rem;
    line-height: 1.6;
    margin-bottom: 2rem;
  }

  .placeholder {
    background: #f0ebe2;
    border: 1px solid #c9b99e;
    border-radius: 6px;
    padding: 1.25rem 1.5rem;
    color: #4a3f35;
  }

  pre {
    margin-top: 0.5rem;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.85rem;
    color: #1c1812;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
    color: #1c1812;
  }

  thead tr {
    background: #e8e1d6;
  }

  th {
    text-align: left;
    padding: 0.6rem 0.75rem;
    font-weight: 600;
    color: #4a3f35;
    border-bottom: 2px solid #c9b99e;
    white-space: nowrap;
  }

  td {
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid #e0d9d0;
    vertical-align: top;
  }

  tr:last-child td {
    border-bottom: none;
  }

  .layer-name {
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  .citation {
    color: #4a3f35;
    max-width: 28rem;
  }

  .feature-count {
    text-align: right;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  .required {
    text-align: center;
  }

  .badge {
    display: inline-block;
    padding: 0.15rem 0.45rem;
    border-radius: 3px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.02em;
  }

  .required-yes {
    background: #f3e6d0;
    color: #7a4a18;
  }

  .required-no {
    background: #e8e8e8;
    color: #666;
  }

  a {
    color: #7a4a18;
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .generated {
    margin-top: 1.5rem;
    font-size: 0.8rem;
    color: #7a6a5a;
  }
</style>
