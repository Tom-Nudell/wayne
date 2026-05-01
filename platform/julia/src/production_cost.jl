# Production cost / market simulation via PowerSimulations.jl.
#
# Default solver is HiGHS (open). When a Gurobi licence is configured, swap
# the solver in `_select_optimizer` without changing the call site.

"""
    run_production_cost(sys::PSY.System;
                        horizon_hours::Int = 24,
                        executor::Executor = LocalCPUExecutor()) -> StudyResult

Run a UC + ED production-cost simulation for the requested horizon and return
nodal LMPs, generation, and congestion. Signal carries solver status,
objective value, and total slack (MW).
"""
function run_production_cost(
    sys::PSY.System;
    horizon_hours::Int = 24,
    executor::Executor = LocalCPUExecutor(),
)::StudyResult
    error("Stub. Wired up after gridagent-data ships its first Sienna bundle.")
end
