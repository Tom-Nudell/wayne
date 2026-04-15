# Shared result envelope. Every study returns one of these so the Python
# verifier sees a uniform shape.

"""
    StudyResult

Envelope for study output.

* `value`   — JSON-serialisable payload (DataFrames already converted to NamedTuples).
* `signal`  — supervisory signal: convergence flags, slack magnitudes,
              monotonicity checks, anything the Python verifier gates on.
* `kind`    — short tag (`"power_flow"`, `"n1_contingency"`, `"production_cost"`).
"""
struct StudyResult
    kind::String
    value::Any
    signal::Dict{String,Any}
end
