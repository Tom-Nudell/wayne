<script lang="ts">
  import { env } from '$env/dynamic/public';
  import MapLibreMap from '$lib/map/MapLibreMap.svelte';
  import StudyPanel from '$lib/study/StudyPanel.svelte';
  import { runStudy } from '$lib/study/client';
  import { wayneLayerIds } from '@wayne/map';
  import type { StudyEvent, StudyFeatureRef, StudyKind } from '@wayne/api';
  import type { FeatureCollection } from 'geojson';

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

  // --- Wayne agent (testability track, dev-flagged) ---------------------
  // Brief §16: behind PUBLIC_WAYNE_AGENT=1 the map can launch an
  // orchestrator study and watch it live. Never set in production.
  const agentEnabled = env.PUBLIC_WAYNE_AGENT === '1';

  let studyEvents = $state<StudyEvent[]>([]);
  let studyRunning = $state(false);
  let studyOpen = $state(false);
  let overlayUrl = $state<string | null>(null);
  let studyAbort: AbortController | null = null;

  // --- DC OPF price surface (LMP choropleth + live what-if slider) ------
  let lmpOverlay = $state<FeatureCollection | null>(null);
  let lmpDomain = $state<{ min: number; max: number } | null>(null);
  let lmpBase: FeatureCollection | null = null; // pristine copy for reset
  let baseObjective = $state<number | null>(null);
  let whatIfObjective = $state<number | null>(null);
  let selectedBus = $state<{ busId: string; lmp: number } | null>(null);
  let whatIfDelta = $state(0);
  let whatIfBusy = $state(false);
  let whatIfError = $state<string | null>(null);
  let whatIfTimer: ReturnType<typeof setTimeout> | null = null;

  async function loadLmpOverlay(url: string) {
    const res = await fetch(url);
    if (!res.ok) return;
    const fc = (await res.json()) as FeatureCollection & {
      metadata?: { objective_usd_per_hour?: number };
    };
    const lmps = fc.features
      .filter((f) => f.properties?.kind === 'lmp')
      .map((f) => Number(f.properties?.lmp_usd_per_mwh ?? 0));
    if (!lmps.length) return;
    lmpBase = structuredClone(fc);
    lmpOverlay = fc;
    // Domain fixed from the base run so colors stay comparable while the
    // slider re-solves.
    lmpDomain = { min: Math.min(...lmps), max: Math.max(...lmps) };
    baseObjective = fc.metadata?.objective_usd_per_hour ?? null;
    whatIfObjective = null;
    selectedBus = null;
    whatIfDelta = 0;
  }

  function selectLmpBus(busId: string, lmp: number) {
    if (!busId) return;
    selectedBus = { busId, lmp };
    whatIfDelta = 0;
    whatIfError = null;
  }

  function scheduleWhatIf() {
    if (whatIfTimer) clearTimeout(whatIfTimer);
    whatIfTimer = setTimeout(runWhatIf, 120);
  }

  async function runWhatIf() {
    const bus = selectedBus;
    if (!bus || !lmpBase) return;
    if (whatIfDelta === 0) {
      lmpOverlay = structuredClone(lmpBase);
      whatIfObjective = null;
      return;
    }
    whatIfBusy = true;
    whatIfError = null;
    try {
      const res = await fetch('/api/solve', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ deltas: { [bus.busId]: whatIfDelta } })
      });
      if (!res.ok) {
        whatIfError = `solve failed: HTTP ${res.status}`;
        return;
      }
      const out = (await res.json()) as {
        objective_usd_per_hour: number | null;
        lmp: Array<{ bus_id: string; lmp_usd_per_mwh: number }>;
      };
      const byBus = new Map(out.lmp.map((r) => [r.bus_id, r.lmp_usd_per_mwh]));
      const next = structuredClone(lmpBase);
      for (const f of next.features) {
        if (f.properties?.kind !== 'lmp') continue;
        const v = byBus.get(String(f.properties.bus_id));
        if (v != null) f.properties.lmp_usd_per_mwh = v;
      }
      lmpOverlay = next;
      whatIfObjective = out.objective_usd_per_hour;
      if (selectedBus) {
        const v = byBus.get(selectedBus.busId);
        if (v != null) selectedBus = { ...selectedBus, lmp: v };
      }
    } catch (err) {
      whatIfError = err instanceof Error ? err.message : String(err);
    } finally {
      whatIfBusy = false;
    }
  }

  async function startStudy(feature: StudyFeatureRef, study: StudyKind = 'n1_contingency') {
    if (studyRunning) return;
    studyEvents = [];
    overlayUrl = null;
    studyOpen = true;
    studyRunning = true;
    studyAbort = new AbortController();
    try {
      await runStudy(
        { fromFeature: feature, study },
        (event) => {
          studyEvents = [...studyEvents, event];
          if (event.event === 'overlay') {
            const urls = event.overlay_urls ?? [event.overlay_url];
            for (const url of urls) {
              if (url.endsWith('dc_opf.geojson')) {
                void loadLmpOverlay(url);
              } else {
                overlayUrl = url;
              }
            }
          }
        },
        studyAbort.signal
      );
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError')) throw err;
    } finally {
      studyRunning = false;
      studyAbort = null;
    }
  }

  function closeStudy() {
    // Aborting the fetch closes the NDJSON stream; the server kills the
    // orchestrator subprocess on cancel, so no orphaned runs pile up.
    studyAbort?.abort();
    studyOpen = false;
    overlayUrl = null;
    lmpOverlay = null;
    lmpDomain = null;
    lmpBase = null;
    selectedBus = null;
    whatIfDelta = 0;
    whatIfObjective = null;
    whatIfError = null;
  }

  const fmtUsd = (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 0 });
</script>

<svelte:head>
  <title>Map · Wayne</title>
</svelte:head>

<div class="map-shell">
  <MapLibreMap
    visibleLayers={visible}
    onRunStudy={agentEnabled ? startStudy : undefined}
    studyOverlayUrl={overlayUrl}
    {lmpOverlay}
    {lmpDomain}
    onSelectLmpBus={agentEnabled ? selectLmpBus : undefined}
  />

  {#if studyOpen}
    <StudyPanel events={studyEvents} running={studyRunning} onClose={closeStudy} />
  {/if}

  {#if lmpOverlay && lmpDomain}
    <aside class="lmp-legend" aria-label="LMP legend">
      <h3>LMP $/MWh</h3>
      <div class="ramp" aria-hidden="true"></div>
      <div class="ends">
        <span>{lmpDomain.min.toFixed(1)}</span>
        <span>{((lmpDomain.min + lmpDomain.max) / 2).toFixed(1)}</span>
        <span>{lmpDomain.max.toFixed(1)}</span>
      </div>
      {#if baseObjective != null}
        <div class="obj">
          system cost:
          {#if whatIfObjective != null}
            <strong>${fmtUsd(whatIfObjective)}/h</strong>
            <small>(base ${fmtUsd(baseObjective)}/h)</small>
          {:else}
            <strong>${fmtUsd(baseObjective)}/h</strong>
          {/if}
        </div>
      {/if}
      {#if selectedBus}
        <div class="whatif">
          <div class="bus">
            bus <strong>{selectedBus.busId}</strong> · {selectedBus.lmp.toFixed(2)} $/MWh
            {#if whatIfBusy}<span class="busy">solving…</span>{/if}
          </div>
          <label>
            demand {whatIfDelta >= 0 ? '+' : ''}{whatIfDelta} MW
            <input
              type="range"
              min="-300"
              max="300"
              step="10"
              bind:value={whatIfDelta}
              oninput={scheduleWhatIf}
            />
          </label>
          {#if whatIfError}<div class="err">{whatIfError}</div>{/if}
        </div>
      {:else}
        <div class="hint">click a price point for a what-if slider</div>
      {/if}
    </aside>
  {/if}

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

  /* --- LMP legend + what-if slider ------------------------------------ */

  .lmp-legend {
    position: absolute;
    bottom: 28px;
    left: 16px;
    z-index: 10;
    background: rgba(243, 237, 224, 0.94);
    border: 1px solid #6b5d4a;
    border-radius: 6px;
    padding: 10px 12px;
    width: 220px;
    color: #1c1812;
    font:
      0.8rem / 1.4 'Inter',
      system-ui,
      sans-serif;
    box-shadow: 0 4px 14px rgba(28, 24, 18, 0.1);
    backdrop-filter: blur(4px);
  }

  .lmp-legend h3 {
    margin: 0 0 6px;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #6b5d4a;
  }

  /* Mirrors LMP_RAMP in MapLibreMap.svelte. */
  .ramp {
    height: 10px;
    border-radius: 5px;
    background: linear-gradient(to right, #2c6e6a, #e8c76f, #c0392b);
    border: 1px solid rgba(28, 24, 18, 0.18);
  }

  .ends {
    display: flex;
    justify-content: space-between;
    font-size: 0.68rem;
    color: #6b5d4a;
    margin-top: 2px;
  }

  .obj {
    margin-top: 8px;
    font-size: 0.75rem;
  }

  .obj small {
    color: #6b5d4a;
  }

  .whatif {
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid rgba(28, 24, 18, 0.12);
  }

  .whatif .bus {
    font-size: 0.75rem;
    margin-bottom: 4px;
  }

  .whatif .busy {
    color: #6b5d4a;
    font-style: italic;
    margin-left: 6px;
  }

  .whatif input[type='range'] {
    width: 100%;
    accent-color: #2c6e6a;
  }

  .whatif label {
    display: block;
    font-size: 0.72rem;
    color: #3b3228;
  }

  .whatif .err {
    color: #c0392b;
    font-size: 0.7rem;
    margin-top: 4px;
  }

  .hint {
    margin-top: 8px;
    font-size: 0.7rem;
    color: #6b5d4a;
    font-style: italic;
  }
</style>
