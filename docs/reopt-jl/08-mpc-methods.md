# Methods

Source: https://natlabrockies.github.io/REopt.jl/dev/mpc/methods/

---

# Methods

`REopt.run_mpc` — Function



```julia
run_mpc(m::JuMP.AbstractModel, fp::String)
```

Solve the model predictive control problem using the `MPCScenario` defined in the JSON file stored at the file path `fp`.

Returns a Dict of results with keys matching those in the `MPCScenario`.



```julia
run_mpc(m::JuMP.AbstractModel,  d::Dict)
```

Solve the model predictive control problem using the `MPCScenario` defined in the dict `d`.

Returns a Dict of results with keys matching those in the `MPCScenario`.



```julia
run_mpc(m::JuMP.AbstractModel, p::MPCInputs)
```

Solve the model predictive control problem using the `MPCInputs`.

Returns a Dict of results with keys matching those in the `MPCScenario`.



```julia
run_mpc(m::JuMP.AbstractModel, ps::AbstractVector{MPCInputs})
```

Solve the model predictive control problem using multiple `MPCInputs`.

Returns a Dict of results with keys matching those in the `MPCScenario`.

`REopt.build_mpc!` — Function



```julia
build_mpc!(m::JuMP.AbstractModel, p::MPCInputs)
```

Add variables and constraints for model predictive control model. Similar to a REopt model but with any length of horizon (instead of one calendar year), and the DER sizes must be provided.



```julia
build_mpc!(m::JuMP.AbstractModel, ps::AbstractVector{MPCInputs})
```

Add variables and constraints for model predictive control model of multiple nodes. Similar to a REopt model but with any length of horizon (instead of one calendar year), and the DER sizes must be provided.
