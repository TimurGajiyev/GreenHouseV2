# Run one REopt scenario with the local REopt.jl and write its results as JSON.
#
#   julia --project=reopt_jl reopt_jl/run.jl <scenario.json> <results.json> [--no-bau] [--gap=0.01] [--time=600]
#
# Defaults are the web tool's: optimality tolerance 1%, time limit 600 s, and a
# BAU scenario solved alongside the optimal one (run_reopt([m1, m2], inputs)),
# which is what fills the *_bau results, NPV, payback and IRR.
using REopt, HiGHS, JuMP, JSON

function load_api_key!()
    for name in ("NLR_DEVELOPER_API_KEY", "NREL_DEVELOPER_API_KEY")
        isempty(strip(get(ENV, name, ""))) || return
    end
    # the same key files the Python calculator falls back to
    for cand in (joinpath(@__DIR__, "..", ".nrel_api_key"), raw"D:\Greenhouse\.nrel_api_key")
        if isfile(cand)
            k = strip(read(cand, String))
            if !isempty(k)
                ENV["NLR_DEVELOPER_API_KEY"] = k
                return
            end
        end
    end
end

function main(args)
    pos = filter(a -> !startswith(a, "--"), args)
    length(pos) == 2 || error("usage: run.jl <scenario.json> <results.json> [--no-bau] [--gap=0.01] [--time=600]")
    function opt(name, default)
        i = findfirst(a -> startswith(a, "--$name="), args)
        return i === nothing ? default : parse(Float64, split(args[i], "=")[2])
    end
    gap, tlim = opt("gap", 0.01), opt("time", 600.0)
    bau = !("--no-bau" in args)

    load_api_key!()
    new_model() = Model(optimizer_with_attributes(HiGHS.Optimizer,
        "mip_rel_gap" => gap, "time_limit" => tlim,
        "output_flag" => false, "log_to_console" => false))

    d = JSON.parsefile(pos[1])
    t0 = time()
    results = bau ? run_reopt([new_model(), new_model()], d) : run_reopt(new_model(), d)
    results["_runner"] = Dict("seconds" => round(time() - t0, digits=1), "mip_rel_gap" => gap,
                              "time_limit" => tlim, "bau" => bau,
                              "reopt_version" => string(pkgversion(REopt)),
                              "highs_version" => string(pkgversion(HiGHS)))
    open(pos[2], "w") do io
        JSON.print(io, results, 1)
    end
    println("status ", get(results, "status", "?"), "  ", round(time() - t0, digits=1), " s  -> ", pos[2])
end

main(ARGS)
