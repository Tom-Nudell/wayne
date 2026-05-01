# N-1 contingency screening via PowerNetworkMatrices.jl LODF.
#
# This is the first study we ship end-to-end (per the plan). LODF is closed-form,
# fast, parallelises trivially across branches, and gives the right first-cut
# answer for an interconnection feasibility study.

"""
    run_n1_contingency(sys::PSY.System;
                       monitored::Union{Nothing,Vector{String}} = nothing,
                       executor::Executor = LocalCPUExecutor()) -> StudyResult

Screen all (or a specified subset of) AC branches with LODF and return the
ranked list of post-contingency overloads.

Signal carries:
* `n_screened` — number of contingencies evaluated
* `n_overloads` — number of monitored branches exceeding rating
* `monotone` — whether the overload severity ranking is monotone in flow
"""
function run_n1_contingency(
    sys::PSY.System;
    monitored::Union{Nothing,Vector{String}} = nothing,
    executor::Executor = LocalCPUExecutor(),
)::StudyResult
    error("Stub. Wired up after gridagent-data ships its first Sienna bundle.")
end
