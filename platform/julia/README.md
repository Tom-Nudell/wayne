# gridagent-julia

Julia execution layer for the gridagent platform. Wraps the NREL Sienna stack
(`PowerSystems.jl`, `PowerFlows.jl`, `PowerNetworkMatrices.jl`,
`PowerSimulations.jl`) behind three callable studies:

- `run_power_flow` — AC power flow
- `run_n1_contingency` — LODF-based N-1 contingency screening (first study)
- `run_production_cost` — UC + ED production cost / market simulation

Every study returns `(result, supervisory_signal)` so the Python orchestrator
can verify-then-advance.

## Executor abstraction

All studies take an `Executor` argument:

- `LocalCPUExecutor` — default, runs inline
- `MadNLPGPUExecutor` — Phase 6, GPU OPF via MadNLP.jl + CUDA.jl
- `DistributedExecutor` — Phase 6, parallel contingency screening

The Python tool surface only changes by accepting a string `executor=` argument.
Execution-backend choice does not propagate up to the agent.

## CLI

Python shells out via:

```bash
julia --project gridagent-julia/run.jl <study> <scenario.json>
```

`scenario.json` carries the change table and the path to the Sienna bundle
produced by `gridagent-data`'s `to_sienna` exporter.

## Status

Skeleton. `load_system` and the executor abstraction are stubbed; study
implementations land after the gridagent-data Sienna export does.
