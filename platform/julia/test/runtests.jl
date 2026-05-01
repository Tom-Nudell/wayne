using Test
using GridAgent

@testset "executor dispatch" begin
    @test GridAgent.executor_from_string("local_cpu") isa GridAgent.LocalCPUExecutor
    @test GridAgent.executor_from_string("madnlp_gpu") isa GridAgent.MadNLPGPUExecutor
    @test GridAgent.executor_from_string("distributed") isa GridAgent.DistributedExecutor
    @test_throws ErrorException GridAgent.executor_from_string("nope")
end
