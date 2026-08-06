<script lang="ts">
  import type { BeneficiaryLoadStudy } from './beneficiary-load';
  import { projectConstraint } from './beneficiary-load';

  interface Props {
    study: BeneficiaryLoadStudy;
    selectedPoiId: string;
    marginalLoadMw: number;
    onSelectPoi: (busId: string) => void;
    onMarginalLoad: (mw: number) => void;
    onClose: () => void;
  }

  let { study, selectedPoiId, marginalLoadMw, onSelectPoi, onMarginalLoad, onClose }: Props =
    $props();

  const selected = $derived(
    study.pois.find((poi) => poi.bus_id === selectedPoiId) ?? study.pois[0]!
  );
  const constraints = $derived(
    selected.constraints.map((constraint) => projectConstraint(constraint, marginalLoadMw))
  );
  const unlockUsed = $derived(
    Math.max(0, Math.min(selected.unlocked_capacity_mw, marginalLoadMw - selected.base_capacity_mw))
  );
  const unlockUsedPct = $derived(
    selected.unlocked_capacity_mw > 0 ? (100 * unlockUsed) / selected.unlocked_capacity_mw : 0
  );

  const fmt = (value: number, digits = 0) =>
    value.toLocaleString(undefined, { maximumFractionDigits: digits });
  const signed = (value: number) => `${value >= 0 ? '+' : ''}${fmt(value, 0)}`;
  const barWidth = (value: number) => `${Math.min(Math.max(value, 0), 112)}%`;
</script>

<aside class="study-panel" aria-label="Beneficiary-load transfer results">
  <header>
    <div>
      <span class="eyebrow">study complete · DC screen</span>
      <h2>POI load unlock</h2>
    </div>
    <button class="close" type="button" aria-label="Close study" onclick={onClose}>×</button>
  </header>

  <div class="summary">
    <div>
      <strong>{study.pois.length}</strong>
      <span>target POIs</span>
    </div>
    <div>
      <strong>{study.ader_nodes.length}</strong>
      <span>ADER nodes</span>
    </div>
    <div>
      <strong>{fmt(study.metadata.screened_constraint_pairs)}</strong>
      <span>constraint pairs</span>
    </div>
  </div>

  <section class="ranking" aria-label="Beneficiary POI ranking">
    <h3>Beneficiaries</h3>
    <div class="poi-list">
      {#each study.pois as poi}
        <button
          type="button"
          class:active={poi.bus_id === selected.bus_id}
          onclick={() => onSelectPoi(poi.bus_id)}
        >
          <span class="rank">{poi.rank}</span>
          <span class="poi-name">{poi.name}<small>bus {poi.bus_id}</small></span>
          <strong>+{fmt(poi.unlocked_capacity_mw, 1)} MW</strong>
        </button>
      {/each}
    </div>
  </section>

  <section class="selected-poi">
    <div class="selected-heading">
      <div>
        <span class="eyebrow"
          >selected load POI · bus {selected.bus_id} · {fmt(selected.existing_load_mw)} MW existing</span
        >
        <h3>{selected.name}</h3>
      </div>
      <div class="unlock">
        <strong>+{fmt(selected.unlocked_capacity_mw, 1)}</strong><span>MW unlocked</span>
      </div>
    </div>

    <div class="capacity-numbers">
      <span>base <strong>{fmt(selected.base_capacity_mw, 1)} MW</strong></span>
      <span>with ADER <strong>{fmt(selected.managed_capacity_mw, 1)} MW</strong></span>
    </div>
    <div class="capacity-track" aria-hidden="true">
      <div
        class="base-band"
        style:width={`${(100 * selected.base_capacity_mw) / selected.managed_capacity_mw}%`}
      ></div>
      <div
        class="unlock-band"
        style:width={`${(100 * selected.unlocked_capacity_mw) / selected.managed_capacity_mw}%`}
      ></div>
      <div
        class="load-marker"
        style:left={`${(100 * marginalLoadMw) / selected.managed_capacity_mw}%`}
      ></div>
    </div>

    <label class="load-slider">
      <span>Marginal additional load withdrawal <strong>{fmt(marginalLoadMw, 1)} MW</strong></span>
      <input
        type="range"
        min="0"
        max={selected.managed_capacity_mw}
        step="1"
        value={marginalLoadMw}
        oninput={(event) => onMarginalLoad(Number(event.currentTarget.value))}
      />
    </label>
    <p class="load-state" class:using-unlock={unlockUsed > 0}>
      {#if unlockUsed > 0}
        ADER mitigation is supporting {fmt(unlockUsed, 1)} MW of this transfer ({fmt(
          unlockUsedPct
        )}% of the unlocked band).
      {:else}
        This transfer remains within the base contingency headroom.
      {/if}
    </p>
  </section>

  <section class="constraints">
    <h3>Limiting relationships</h3>
    <p class="section-note">Projected loading at the selected marginal withdrawal.</p>
    {#each constraints as constraint}
      <article>
        <div class="constraint-title">
          <strong>{constraint.monitored_branch_id}</strong>
          <span>during outage {constraint.outage_branch_id}</span>
          <em>+{fmt(constraint.transfer_gain_mw, 1)} MW headroom</em>
        </div>
        <div class="comparison-row">
          <span>no ADER</span>
          <div class="bar">
            <i class="counterfactual" style:width={barWidth(constraint.counterfactual_loading_pct)}
            ></i>
          </div>
          <strong class:over={constraint.counterfactual_loading_pct > 100}
            >{fmt(constraint.counterfactual_loading_pct, 1)}%</strong
          >
        </div>
        <div class="comparison-row">
          <span>with ADER</span>
          <div class="bar">
            <i class="managed" style:width={barWidth(constraint.projected_loading_pct)}></i>
          </div>
          <strong class:over={constraint.projected_loading_pct > 100}
            >{fmt(constraint.projected_loading_pct, 1)}%</strong
          >
        </div>
      </article>
    {/each}
  </section>

  <section class="dispatch">
    <h3>Assumed ADER action</h3>
    <div class="dispatch-grid">
      {#each study.ader_nodes as node}
        <span class:withdrawal={node.dispatch_mw < 0}
          >{node.name} {signed(node.dispatch_mw)} MW</span
        >
      {/each}
    </div>
    <p>
      Net ADER {signed(study.metadata.ader_net_dispatch_mw)} MW; BA reference
      {signed(study.metadata.ba_reference_dispatch_mw)} MW. Added POI load is a separate BA-to-POI transfer.
    </p>
  </section>

  <footer>
    Assumed ADER and target-POI sets on RTS-GMLC · {study.metadata.model} ·
    {study.metadata.emergency_rating_multiplier.toFixed(2)}× emergency ratings ·
    {study.metadata.islanding_outages_excluded} islanding outages excluded. Sensitivity bound, not an
    AC-feasible dispatch.
  </footer>
</aside>

<style>
  .study-panel {
    position: absolute;
    top: 16px;
    right: 16px;
    bottom: 28px;
    z-index: 12;
    width: min(390px, calc(100vw - 32px));
    overflow-y: auto;
    background: rgba(250, 246, 236, 0.97);
    border: 1px solid #6b5d4a;
    border-radius: 10px;
    box-shadow: 0 12px 36px rgba(28, 24, 18, 0.18);
    color: #1c1812;
    font:
      0.78rem/1.4 'Inter',
      system-ui,
      sans-serif;
    backdrop-filter: blur(7px);
  }

  header,
  section,
  footer {
    padding: 14px 16px;
  }

  header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    border-bottom: 1px solid rgba(28, 24, 18, 0.12);
  }

  h2,
  h3,
  p {
    margin: 0;
  }

  h2 {
    margin-top: 2px;
    font:
      650 1.12rem/1.2 'Inter',
      system-ui,
      sans-serif;
  }

  h3 {
    font:
      650 0.82rem/1.25 'Inter',
      system-ui,
      sans-serif;
  }

  .eyebrow {
    color: #6b5d4a;
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.09em;
    text-transform: uppercase;
  }

  .close {
    border: 0;
    background: transparent;
    color: #6b5d4a;
    cursor: pointer;
    font-size: 1.35rem;
    line-height: 1;
  }

  .summary {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1px;
    background: rgba(28, 24, 18, 0.1);
    border-bottom: 1px solid rgba(28, 24, 18, 0.12);
  }

  .summary div {
    padding: 10px 8px;
    background: #f3ede0;
    text-align: center;
  }

  .summary strong,
  .summary span {
    display: block;
  }

  .summary strong {
    font-size: 0.92rem;
  }

  .summary span {
    color: #6b5d4a;
    font-size: 0.61rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  section + section,
  footer {
    border-top: 1px solid rgba(28, 24, 18, 0.1);
  }

  .ranking {
    padding-bottom: 10px;
  }

  .poi-list {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 5px;
    margin-top: 8px;
  }

  .poi-list button {
    display: grid;
    grid-template-columns: 18px 1fr;
    gap: 0 5px;
    align-items: center;
    padding: 7px;
    border: 1px solid rgba(28, 24, 18, 0.14);
    border-radius: 6px;
    background: rgba(243, 237, 224, 0.6);
    color: #1c1812;
    cursor: pointer;
    text-align: left;
  }

  .poi-list button:hover,
  .poi-list button.active {
    border-color: #3aa17a;
    background: rgba(58, 161, 122, 0.1);
  }

  .rank {
    grid-row: 1 / 3;
    display: grid;
    place-items: center;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: #6b5d4a;
    color: #faf6ec;
    font-size: 0.62rem;
  }

  .poi-name {
    font-weight: 650;
    line-height: 1.1;
  }

  .poi-name small {
    display: block;
    margin-top: 2px;
    color: #6b5d4a;
    font-size: 0.6rem;
    font-weight: 400;
  }

  .poi-list button > strong {
    grid-column: 2;
    color: #287a5c;
    font-size: 0.68rem;
  }

  .selected-heading,
  .capacity-numbers,
  .constraint-title {
    display: flex;
    justify-content: space-between;
    gap: 10px;
  }

  .selected-heading h3 {
    margin-top: 2px;
    font-size: 1rem;
  }

  .unlock {
    text-align: right;
  }

  .unlock strong,
  .unlock span {
    display: block;
  }

  .unlock strong {
    color: #287a5c;
    font-size: 1.15rem;
  }

  .unlock span {
    color: #6b5d4a;
    font-size: 0.6rem;
    text-transform: uppercase;
  }

  .capacity-numbers {
    margin-top: 12px;
    color: #6b5d4a;
    font-size: 0.68rem;
  }

  .capacity-numbers strong {
    color: #1c1812;
  }

  .capacity-track {
    position: relative;
    display: flex;
    height: 9px;
    margin: 5px 0 11px;
    overflow: visible;
    border-radius: 5px;
    background: rgba(28, 24, 18, 0.1);
  }

  .base-band {
    border-radius: 5px 0 0 5px;
    background: #c9b896;
  }

  .unlock-band {
    border-radius: 0 5px 5px 0;
    background: #3aa17a;
  }

  .load-marker {
    position: absolute;
    top: -4px;
    width: 2px;
    height: 17px;
    transform: translateX(-1px);
    background: #1c1812;
  }

  .load-slider {
    display: block;
  }

  .load-slider span {
    display: flex;
    justify-content: space-between;
    gap: 8px;
  }

  .load-slider input {
    width: 100%;
    margin: 7px 0 0;
    accent-color: #3aa17a;
  }

  .load-state {
    margin-top: 5px;
    padding: 7px 8px;
    border-radius: 5px;
    background: rgba(201, 184, 150, 0.2);
    color: #6b5d4a;
    font-size: 0.68rem;
  }

  .load-state.using-unlock {
    background: rgba(58, 161, 122, 0.1);
    color: #287a5c;
  }

  .section-note {
    margin-top: 2px;
    color: #6b5d4a;
    font-size: 0.65rem;
  }

  .constraints article {
    margin-top: 9px;
    padding: 8px;
    border: 1px solid rgba(28, 24, 18, 0.1);
    border-radius: 6px;
    background: rgba(243, 237, 224, 0.55);
  }

  .constraint-title {
    align-items: baseline;
    margin-bottom: 6px;
    font-size: 0.66rem;
  }

  .constraint-title strong {
    font-size: 0.75rem;
  }

  .constraint-title span {
    flex: 1;
    color: #6b5d4a;
  }

  .constraint-title em {
    color: #287a5c;
    font-size: 0.61rem;
    font-style: normal;
    white-space: nowrap;
  }

  .comparison-row {
    display: grid;
    grid-template-columns: 52px 1fr 40px;
    gap: 6px;
    align-items: center;
    margin-top: 4px;
    font-size: 0.61rem;
  }

  .comparison-row > span {
    color: #6b5d4a;
  }

  .comparison-row > strong {
    text-align: right;
  }

  .comparison-row > strong.over {
    color: #c0392b;
  }

  .bar {
    height: 5px;
    overflow: hidden;
    border-radius: 3px;
    background: rgba(28, 24, 18, 0.1);
  }

  .bar i {
    display: block;
    height: 100%;
  }

  .bar .counterfactual {
    background: #c0392b;
  }

  .bar .managed {
    background: #3aa17a;
  }

  .dispatch-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    margin-top: 7px;
  }

  .dispatch-grid span {
    padding: 3px 6px;
    border-radius: 12px;
    background: rgba(58, 161, 122, 0.12);
    color: #287a5c;
    font-size: 0.64rem;
    font-weight: 650;
  }

  .dispatch-grid span.withdrawal {
    background: rgba(139, 90, 43, 0.12);
    color: #8b5a2b;
  }

  .dispatch p {
    margin-top: 7px;
    color: #6b5d4a;
    font-size: 0.65rem;
  }

  footer {
    color: #6b5d4a;
    font-size: 0.61rem;
  }

  @media (max-width: 700px) {
    .study-panel {
      top: auto;
      max-height: 72vh;
    }
  }
</style>
