<script lang="ts">
  import { BRAND } from '@wayne/ui/brand';

  // Last updated: keep in sync with actual policy text.
  const LAST_UPDATED = '2026-05-08';
</script>

<svelte:head>
  <title>Privacy Policy · {BRAND.productName ?? BRAND.internal}</title>
</svelte:head>

<main>
  <h1>Privacy Policy</h1>
  <p class="meta">
    Last updated: {new Date(LAST_UPDATED).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    })}
  </p>

  <section>
    <h2>Summary</h2>
    <p>
      We collect minimal data, do not sell it, and do not run third-party advertising pixels.
      First-party analytics (Vercel Web Analytics) are used to understand aggregate usage.
    </p>
  </section>

  <section>
    <h2>Information we collect</h2>
    <ul>
      <li>
        <strong>Account data</strong> — email address and name when you create an account (Pro tier only).
      </li>
      <li>
        <strong>Usage data</strong> — pages visited, map interactions, feature toggles. Collected in aggregate
        via Vercel Web Analytics (first-party, no cross-site tracking).
      </li>
      <li>
        <strong>Error data</strong> — browser errors and performance traces collected via Sentry to help
        us fix bugs. Session Replay is enabled for Pro users only, with form fields redacted.
      </li>
      <li>
        <strong>Payment data</strong> — handled entirely by Stripe. We never see or store full card numbers.
      </li>
    </ul>
  </section>

  <section>
    <h2>Cookies</h2>
    <p>
      We use cookies only for authentication session management (Clerk). We do not use advertising
      cookies. No cookie consent banner is required because we run no third-party marketing pixels.
    </p>
  </section>

  <section>
    <h2>Data sharing</h2>
    <p>
      We share data only with the sub-processors required to operate the service: Vercel (hosting),
      Clerk (auth), Stripe (billing), Cloudflare (CDN/tiles), Sentry (error monitoring), PostHog
      (product analytics), Neon (database), Upstash (rate limiting). A full sub-processor list is
      available on request.
    </p>
    <p>We do not sell or rent personal data to third parties.</p>
  </section>

  <section>
    <h2>Data retention</h2>
    <p>
      Account data is retained for the life of your account plus 90 days after deletion. Usage and
      error data follows the default retention of each sub-processor (typically 90 days).
    </p>
  </section>

  <section>
    <h2>Your rights</h2>
    <p>
      You may request access to, correction of, or deletion of your personal data at any time.
      California residents have additional rights under CCPA/CPRA. EU residents have rights under
      GDPR. To exercise these rights, email us at the address on the contact page.
    </p>
  </section>

  <section>
    <h2>Changes to this policy</h2>
    <p>
      We will update this page when the policy changes and notify registered users by email for
      material changes.
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
</style>
