<script lang="ts">
  import type { StudyEvent } from '@wayne/api';

  type StepEvent = Extract<StudyEvent, { event: 'step' }>;
  type WorkflowEvent = Extract<StudyEvent, { event: 'workflow' }>;
  type EscalateEvent = Extract<StudyEvent, { event: 'escalate' }>;

  interface Props {
    events: readonly StudyEvent[];
    running: boolean;
    onClose: () => void;
  }

  const { events, running, onClose }: Props = $props();

  const steps = $derived(events.filter((e): e is StepEvent => e.event === 'step'));
  const workflow = $derived(events.find((e): e is WorkflowEvent => e.event === 'workflow'));
  const escalation = $derived(events.find((e): e is EscalateEvent => e.event === 'escalate'));
  const finish = $derived(events.find((e) => e.event === 'finish'));
  const errors = $derived(events.filter((e) => e.event === 'error'));
  const overlay = $derived(events.find((e) => e.event === 'overlay'));
  const start = $derived(events.find((e) => e.event === 'start'));

  // Steps the planner chose itself — everything in a non-workflow run, or
  // the post-escalation tail of a workflow run.
  const agentSteps = $derived(steps.filter((s) => !s.node));

  function nodeSteps(id: string): StepEvent[] {
    return steps.filter((s) => s.node === id);
  }

  // A workflow announces its full plan before anything runs, so every node
  // renders immediately and ticks through states as steps arrive. This is
  // the trust payoff of fixed workflows: the plan is visible up front,
  // deterministic steps are marked apart from model-chosen ones.
  type NodeState =
    | 'pending'
    | 'active'
    | 'done'
    | 'retrying'
    | 'escalated'
    | 'aborted'
    | 'skipped';

  function nodeState(id: string): NodeState {
    const last = nodeSteps(id).at(-1);
    if (last) {
      if (last.decision === 'advance') return 'done';
      if (last.decision === 'abort') return 'aborted';
      if (last.decision === 'retry') return running && !escalation ? 'retrying' : 'escalated';
      return 'escalated';
    }
    if (escalation || finish || errors.length > 0) return 'skipped';
    if (!workflow || !running) return 'pending';
    const firstIdle = workflow.nodes.find((n) => nodeSteps(n.id).length === 0);
    return firstIdle?.id === id ? 'active' : 'pending';
  }

  const NODE_BADGE: Record<NodeState, string> = {
    pending: '·',
    active: '◌',
    done: '✓',
    retrying: '↻',
    escalated: '⚠',
    aborted: '✕',
    skipped: '—'
  };

  function signalSummary(signal: Record<string, unknown>): string {
    return Object.entries(signal)
      .filter(([k]) => !k.startsWith('_'))
      .map(([k, v]) => `${k}=${typeof v === 'number' ? Number(v.toFixed?.(2) ?? v) : v}`)
      .join(' ')
      .slice(0, 90);
  }
</script>

<aside class="study-panel" aria-label="Agent study progress" aria-live="polite">
  <header>
    <h2>
      {#if running}<span class="pulse" aria-hidden="true"></span>{/if}
      Wayne study
      {#if start && start.event === 'start'}
        <span class="episode">· {start.episode_id}</span>
      {/if}
    </h2>
    <button type="button" onclick={onClose} aria-label="Close study panel">×</button>
  </header>

  {#if start && start.event === 'start'}
    <p class="goal">{start.goal}</p>
  {/if}

  {#if workflow}
    <p class="wf-name">workflow · {workflow.workflow}</p>
    <ol class="nodes">
      {#each workflow.nodes as node (node.id)}
        {@const state = nodeState(node.id)}
        {@const ns = nodeSteps(node.id)}
        {@const last = ns.at(-1)}
        <li class="node-{state}">
          <span class="badge" aria-hidden="true">{NODE_BADGE[state]}</span>
          <span class="tool">{node.tool}</span>
          <span class="signal">{last ? signalSummary(last.signal) : ''}</span>
          <span class="state">{state}{ns.length > 1 ? ` ×${ns.length}` : ''}</span>
        </li>
      {/each}
    </ol>
    {#if escalation}
      <p class="escalate">
        workflow escalated at <strong>{escalation.node}</strong> — agent takes over
      </p>
    {/if}
  {/if}

  {#if (!workflow || escalation) && agentSteps.length > 0}
    <ol class="agent-steps">
      {#each agentSteps as step (step.step)}
        <li class="verdict-{step.decision}">
          <span class="tool">{step.tool}</span>
          <span class="signal">{signalSummary(step.signal)}</span>
          <span class="verdict">{step.decision}{step.attempt > 1 ? ` ×${step.attempt}` : ''}</span>
        </li>
      {/each}
    </ol>
  {/if}

  {#if running && !finish}
    <p class="thinking">
      {workflow && !escalation ? 'running workflow…' : 'planner thinking…'}
    </p>
  {/if}

  {#if finish && finish.event === 'finish'}
    <div class="summary">
      <h3>Summary</h3>
      <p>{finish.summary}</p>
      {#if overlay && overlay.event === 'overlay'}
        <p class="overlay-note">
          {overlay.feature_count} overloaded branch{overlay.feature_count === 1 ? '' : 'es'} drawn on
          the map.
        </p>
      {/if}
    </div>
  {/if}

  {#each errors as err, i (i)}
    {#if err.event === 'error'}
      <p class="error">{err.message}</p>
    {/if}
  {/each}
</aside>

<style>
  .study-panel {
    position: absolute;
    top: 16px;
    right: 16px;
    z-index: 20;
    width: 340px;
    max-height: calc(100vh - 32px);
    overflow-y: auto;
    background: rgba(243, 237, 224, 0.96);
    border: 1px solid #6b5d4a;
    border-radius: 6px;
    padding: 12px 14px;
    color: #1c1812;
    font:
      0.8rem/1.45 'Inter',
      system-ui,
      sans-serif;
    box-shadow: 0 4px 14px rgba(28, 24, 18, 0.12);
    backdrop-filter: blur(4px);
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  h2 {
    margin: 0;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #6b5d4a;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .episode {
    text-transform: none;
    letter-spacing: 0;
    font-weight: 400;
  }

  header button {
    background: none;
    border: none;
    font-size: 1.1rem;
    color: #6b5d4a;
    cursor: pointer;
    line-height: 1;
  }

  .pulse {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #6f8a52;
    animation: pulse 1.2s ease-in-out infinite;
  }

  @keyframes pulse {
    50% {
      opacity: 0.25;
    }
  }

  .goal {
    margin: 8px 0;
    font-style: italic;
    color: #3b3228;
  }

  .wf-name {
    margin: 8px 0 2px;
    font-size: 0.65rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #6b5d4a;
  }

  ol {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  li {
    display: grid;
    gap: 8px;
    padding: 4px 0;
    border-top: 1px solid rgba(28, 24, 18, 0.08);
    align-items: baseline;
  }

  .nodes li {
    grid-template-columns: 14px auto 1fr auto;
  }

  .agent-steps li {
    grid-template-columns: auto 1fr auto;
  }

  .badge {
    text-align: center;
    font-weight: 700;
  }

  .tool {
    font-weight: 600;
    white-space: nowrap;
  }

  .signal {
    color: #6b5d4a;
    font-size: 0.7rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .verdict,
  .state {
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  /* Alarm colors are earned: green advances quietly, yellow re-plans,
     red ends the run — mirrors the CLI renderer. Pending/skipped nodes
     stay muted so the eye lands on what's happening now. */
  .node-pending,
  .node-skipped {
    opacity: 0.45;
  }

  .node-active .badge,
  .node-active .state {
    color: #6f8a52;
  }

  .node-done .badge,
  .node-done .state {
    color: #3aa17a;
  }

  .node-retrying .badge,
  .node-retrying .state,
  .node-escalated .badge,
  .node-escalated .state {
    color: #b07d2b;
  }

  .node-aborted .badge,
  .node-aborted .state {
    color: #c0392b;
  }

  .verdict-advance .verdict {
    color: #3aa17a;
  }
  .verdict-retry .verdict,
  .verdict-replan .verdict {
    color: #b07d2b;
  }
  .verdict-abort .verdict {
    color: #c0392b;
  }

  .escalate {
    margin: 6px 0 0;
    padding: 4px 6px;
    border-left: 2px solid #b07d2b;
    color: #7a5a20;
    font-size: 0.7rem;
  }

  .thinking {
    color: #6b5d4a;
    font-style: italic;
    margin: 6px 0 0;
  }

  .summary {
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid rgba(28, 24, 18, 0.18);
  }

  .summary h3 {
    margin: 0 0 4px;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #6b5d4a;
  }

  .summary p {
    margin: 0 0 4px;
    white-space: pre-wrap;
  }

  .overlay-note {
    color: #c0392b;
    font-weight: 600;
  }

  .error {
    margin: 8px 0 0;
    color: #c0392b;
    font-size: 0.7rem;
    white-space: pre-wrap;
  }
</style>
