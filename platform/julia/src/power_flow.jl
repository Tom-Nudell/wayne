# AC power flow study.

include("result.jl")

"""
    run_power_flow(sys::PSY.System; executor::Executor = LocalCPUExecutor()) -> StudyResult

Solve AC power flow on `sys`. Returns a `StudyResult` whose `signal` carries
the convergence flag and the worst per-bus mismatch in MW so the Python
verifier can decide whether to advance.
"""
function run_power_flow(sys::PSY.System; executor::Executor = LocalCPUExecutor())::StudyResult
    error("Stub. Wired up after gridagent-data ships its first Sienna bundle.")
end
