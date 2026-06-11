<script lang="ts">
  import { BRAND } from '@wayne/ui/brand';
</script>

<svelte:head>
  <title>About · {BRAND.productName ?? BRAND.internal}</title>
</svelte:head>

<main>
  <h1>About</h1>

  <section>
    <h2>What this is</h2>
    <p>
      {BRAND.productName ?? BRAND.internal} is a commercial-grade interactive map of US energy
      infrastructure — power plants, transmission lines, substations, gas pipelines, planned
      upgrades, and EV charging stations. Every feature on the map has audit-grade lineage:
      you can click any feature and see exactly which public dataset it came from, its license,
      and when it was ingested.
    </p>
  </section>

  <section>
    <h2>Data sources</h2>
    <p>
      All data is sourced from public US government and open datasets — EIA, HIFLD, OSM, AFDC,
      and others. No commercially restricted data is included without a confirmed open license.
      For the full source list, license matrix, and required attributions, see the
      <a href="/attribution">attribution page</a>.
    </p>
  </section>

  <section>
    <h2>Important disclaimer</h2>
    <p>
      This map is for <strong>general information and exploration only</strong>. It must not be
      used as the basis for engineering decisions, grid operations, financial transactions, or
      emergency response. Data may be incomplete, outdated, or contain errors. Always consult
      authoritative primary sources and qualified professionals for any operational decision.
    </p>
  </section>

  <section>
    <h2>Contact</h2>
    <p>
      Questions, corrections, or data issues: use the feedback link in the map or email us
      once the domain is confirmed.
    </p>
  </section>
</main>

<style>
  main {
    max-width: 52rem;
    margin: 3rem auto;
    padding: 0 1.5rem;
    color: #1c1812;
    line-height: 1.65;
  }

  h1 {
    font-size: 1.6rem;
    font-weight: 600;
    margin-bottom: 2rem;
  }

  h2 {
    font-size: 1.05rem;
    font-weight: 600;
    margin: 2rem 0 0.5rem;
    color: #3a2e24;
  }

  p {
    color: #4a3f35;
    margin: 0;
  }

  section + section {
    border-top: 1px solid #e0d9d0;
    padding-top: 1.5rem;
    margin-top: 0.5rem;
  }

  strong {
    color: #1c1812;
  }

  a {
    color: #7a4a18;
    text-decoration: underline;
    text-underline-offset: 2px;
  }
</style>
