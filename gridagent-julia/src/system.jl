# System loading. Bridges the gridagent-data Sienna export to PowerSystems.jl.
#
# The bundle layout written by `gridagent_data.exporters.to_sienna.export` is:
#
#     <bundle>/sienna/case.m              MATPOWER case
#     <bundle>/sienna/case_eia.json       EIA ID sidecar (matches MATPOWER indices)
#     <bundle>/sienna/profiles/*.csv      Time series, optional
#
# We round-trip the EIA IDs into PowerSystems `ext` fields so result rows can
# rejoin the warehouse without an indirection.

using JSON3

"""
    load_system(bundle::AbstractString) -> PSY.System

Load a Sienna bundle, attaching EIA IDs to each component as `ext` metadata.
"""
function load_system(bundle::AbstractString)::PSY.System
    case_path = joinpath(bundle, "sienna", "case.m")
    sidecar_path = joinpath(bundle, "sienna", "case_eia.json")
    isfile(case_path) || error("Missing MATPOWER case at $(case_path)")

    sys = PSY.System(case_path)

    if isfile(sidecar_path)
        sidecar = JSON3.read(read(sidecar_path, String))
        annotate_eia_ids!(sys, sidecar)
    end
    return sys
end

"""Tag each component with its canonical gridagent ID for round-trip joins."""
function annotate_eia_ids!(sys::PSY.System, sidecar)
    for (name, eia_id) in get(sidecar, :generators, ())
        gen = PSY.get_component(PSY.Generator, sys, String(name))
        gen === nothing && continue
        PSY.set_ext!(gen, Dict("gridagent_id" => String(eia_id)))
    end
    return sys
end
