#!/usr/bin/env julia
# CLI entrypoint: `julia --project run.jl <study> <scenario.json>`
#
# Python tool wrappers in gridagent-tools shell out to this. Subprocess (rather
# than PythonCall/JuliaCall) is chosen for debuggability and crash isolation;
# revisit if startup latency becomes a problem.

using Pkg
Pkg.activate(@__DIR__)

using JSON3
using GridAgent

const STUDIES = Dict(
    "power_flow"      => GridAgent.run_power_flow,
    "n1_contingency"  => GridAgent.run_n1_contingency,
    "production_cost" => GridAgent.run_production_cost,
)

function main(args::Vector{String})
    length(args) == 2 || error("Usage: julia run.jl <study> <scenario.json>")
    study_name, scenario_path = args
    haskey(STUDIES, study_name) || error("Unknown study: $study_name")

    scenario = JSON3.read(read(scenario_path, String))
    sys = GridAgent.load_system(scenario.bundle)

    executor = GridAgent.executor_from_string(get(scenario, :executor, "local_cpu"))
    kwargs = get(scenario, :kwargs, Dict())

    result = STUDIES[study_name](sys; executor = executor, kwargs...)

    JSON3.pretty(stdout, Dict(
        "kind"   => result.kind,
        "value"  => result.value,
        "signal" => result.signal,
    ))
    println()
end

main(ARGS)
