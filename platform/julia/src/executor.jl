# Executor abstraction.
#
# Every study takes an `Executor` argument. The Python tool surface only sees a
# string (`"local_cpu"`, `"madnlp_gpu"`, `"distributed"`); construction lives
# here. Adding a backend = add a concrete subtype + a `dispatch` method per
# study, no change to the tool surface.

abstract type Executor end

"""LocalCPUExecutor — the default. Runs everything inline on this Julia process."""
struct LocalCPUExecutor <: Executor end

"""MadNLPGPUExecutor — Phase 6. OPF on GPU via MadNLP.jl + CUDA.jl."""
struct MadNLPGPUExecutor <: Executor
    device_id::Int
    MadNLPGPUExecutor(; device_id::Int = 0) = new(device_id)
end

"""DistributedExecutor — Phase 6. Parallel contingency screening via Distributed.jl."""
struct DistributedExecutor <: Executor
    n_workers::Int
    DistributedExecutor(; n_workers::Int = 4) = new(n_workers)
end

"""executor_from_string(name) — build an Executor from the string the Python
tool surface passes in."""
function executor_from_string(name::AbstractString)::Executor
    name == "local_cpu" && return LocalCPUExecutor()
    name == "madnlp_gpu" && return MadNLPGPUExecutor()
    name == "distributed" && return DistributedExecutor()
    error("Unknown executor: $name")
end
