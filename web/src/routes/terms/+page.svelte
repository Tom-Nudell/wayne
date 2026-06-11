<script lang="ts">
  import { BRAND } from '@wayne/ui/brand';

  const LAST_UPDATED = '2026-05-08';
</script>

<svelte:head>
  <title>Terms of Service · {BRAND.productName ?? BRAND.internal}</title>
</svelte:head>

<main>
  <h1>Terms of Service</h1>
  <p class="meta">
    Last updated: {new Date(LAST_UPDATED).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    })}
  </p>

  <section>
    <h2>Acceptance</h2>
    <p>
      By accessing or using {BRAND.productName ?? BRAND.internal} ("the Service") you agree to these Terms.
      If you do not agree, do not use the Service.
    </p>
  </section>

  <section>
    <h2>Description of service</h2>
    <p>
      The Service provides an interactive map of publicly sourced US energy infrastructure data for
      general information and exploration purposes.
    </p>
  </section>

  <section>
    <h2>Not for operational use — important disclaimer</h2>
    <p>
      <strong>
        The Service must not be used as the basis for engineering decisions, grid operations, power
        system planning, financial transactions, real estate decisions, emergency response, or any
        other decision where accuracy is safety-critical or legally material.
      </strong>
    </p>
    <p>
      Data may be incomplete, outdated, geographically misplaced, or otherwise inaccurate. Always
      consult authoritative primary sources and qualified professionals.
    </p>
  </section>

  <section>
    <h2>Permitted use</h2>
    <p>
      You may use the Service for personal exploration, research, journalism, and internal business
      purposes consistent with these Terms. You may not:
    </p>
    <ul>
      <li>Scrape or systematically extract the Service's data at scale.</li>
      <li>Use the Service to build a competing product without a commercial license.</li>
      <li>
        Re-publish raw data exports in violation of the original source licenses (see the <a
          href="/attribution">attribution page</a
        >).
      </li>
      <li>Attempt to circumvent tier gating or access controls.</li>
    </ul>
  </section>

  <section>
    <h2>Data attribution</h2>
    <p>
      Some data sources require attribution when their data is reproduced. If you publish outputs
      derived from the Service (screenshots, reports, exports), you must include the attributions
      listed on the <a href="/attribution">attribution page</a> for any layer you used. ODbL-licensed
      layers (OSM-derived) may not be exported as raw GeoJSON without a commercial license.
    </p>
  </section>

  <section>
    <h2>Accounts and billing</h2>
    <p>
      Pro tier subscriptions are billed monthly or annually via Stripe. You may cancel at any time;
      access continues until the end of the billing period. Refunds are at our discretion for annual
      plans cancelled within 14 days.
    </p>
  </section>

  <section>
    <h2>Disclaimer of warranties</h2>
    <p>
      THE SERVICE IS PROVIDED "AS IS" WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. WE DO NOT
      WARRANT ACCURACY, COMPLETENESS, TIMELINESS, OR FITNESS FOR ANY PARTICULAR PURPOSE.
    </p>
  </section>

  <section>
    <h2>Limitation of liability</h2>
    <p>
      TO THE MAXIMUM EXTENT PERMITTED BY LAW, OUR TOTAL LIABILITY FOR ANY CLAIM ARISING FROM USE OF
      THE SERVICE IS LIMITED TO THE AMOUNT YOU PAID US IN THE 12 MONTHS PRECEDING THE CLAIM. WE ARE
      NOT LIABLE FOR INDIRECT, INCIDENTAL, OR CONSEQUENTIAL DAMAGES.
    </p>
  </section>

  <section>
    <h2>Changes to terms</h2>
    <p>
      We may update these Terms. Material changes will be announced by email to registered users
      with at least 14 days notice. Continued use after the effective date constitutes acceptance.
    </p>
  </section>

  <section>
    <h2>Governing law</h2>
    <p>
      These Terms are governed by the laws of the state of incorporation (TBD upon entity
      formation), without regard to conflict of law principles.
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
    margin-bottom: 0.25rem;
  }

  .meta {
    font-size: 0.8rem;
    color: #7a6a5a;
    margin-bottom: 2rem;
  }

  h2 {
    font-size: 1.05rem;
    font-weight: 600;
    margin: 2rem 0 0.5rem;
    color: #3a2e24;
  }

  p,
  ul {
    color: #4a3f35;
    margin: 0 0 0.75rem;
  }

  ul {
    padding-left: 1.4rem;
  }

  li {
    margin-bottom: 0.4rem;
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
