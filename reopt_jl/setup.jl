# One-time setup of the local REopt.jl environment.
#
#   julia --project=reopt_jl reopt_jl/setup.jl
#
# REopt is taken from ../REopt (the v0.61.1 source this repository ports from),
# not from the registry, so the reference runs and our ports read the same code.
using Pkg

Pkg.develop(path=joinpath(@__DIR__, "..", "REopt"))
Pkg.add(["HiGHS", "JuMP", "JSON"])
# The resolver picks ArchGDAL 0.9.3, which will not precompile on Julia 1.10
# ("Method overwriting is not permitted"); REopt's own Manifest uses 0.9.4.
Pkg.add(name="ArchGDAL", version="0.9.4")
Pkg.pin("ArchGDAL")
Pkg.instantiate()
Pkg.precompile()

using REopt, HiGHS, JuMP
println("REopt ", pkgversion(REopt), ", HiGHS ", pkgversion(HiGHS), ", JuMP ", pkgversion(JuMP))
