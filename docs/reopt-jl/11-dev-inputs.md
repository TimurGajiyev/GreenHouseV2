# The REoptInputs structure

Source: https://natlabrockies.github.io/REopt.jl/dev/developer/inputs/

---

# The REoptInputs structure

The REoptInputs structure uses the Scenario to build all of the data necessary to construct the JuMP mathematical model.

## REoptInputs

`REopt.REoptInputs` — Type



```julia
REoptInputs
```

The data structure for all the inputs necessary to construct the JuMP model.


```julia
struct REoptInputs <: AbstractInputs
    s::ScenarioType
    techs::Techs
    min_sizes::Dict{String, <:Real}  # (techs)
    max_sizes::Dict{String, <:Real}  # (techs)
    existing_sizes::Dict{String, <:Real}  # (techs)
    cap_cost_slope::Dict{String, Any}  # (techs)
    om_cost_per_kw::Dict{String, <:Real}  # (techs)
    thermal_cop::Dict{String, <:Real}  # (techs.absorption_chiller)
    time_steps::UnitRange
    time_steps_with_grid::Array{Int, 1}
    time_steps_without_grid::Array{Int, 1}
    hours_per_time_step::Real
    months::UnitRange
    production_factor::DenseAxisArray{<:Real, 2}  # (techs, time_steps)
    levelization_factor::Dict{String, <:Real,}  # (techs)
    value_of_lost_load_per_kwh::Array{<:Real, 1}
    pwf_e::Real
    pwf_om::Real
    pwf_fuel::Dict{String, <:Real}
    pwf_emissions_cost::Dict{String, Float64} # Cost of emissions present worth factors for grid and onsite fuelburn emissions [unitless]
    pwf_grid_emissions::Dict{String, Float64} # Emissions [lbs] present worth factors for grid emissions [unitless]
    pwf_offtaker::Real 
    pwf_owner::Real
    third_party_factor::Real
    pvlocations::Array{Symbol, 1}
    maxsize_pv_locations::DenseAxisArray{<:Real, 1}  # indexed on pvlocations
    pv_to_location::Dict{String, Dict{Symbol, Int64}}  # (techs.pv, pvlocations)
    ratchets::UnitRange
    techs_by_exportbin::Dict{Symbol, AbstractArray}  # keys can include [:NEM, :WHL, :EXC]
    export_bins_by_tech::Dict
    storage_by_exportbin::Dict{Symbol, AbstractArray}  # keys can include [:NEM, :WHL, :EXC]
    export_bins_by_storage::Dict
    n_segs_by_tech::Dict{String, Int}
    seg_min_size::Dict{String, Dict{Int, <:Real}}
    seg_max_size::Dict{String, Dict{Int, <:Real}}
    seg_yint::Dict{String, Dict{Int, <:Real}}
    pbi_pwf::Dict{String, Any}  # (pbi_techs)
    pbi_max_benefit::Dict{String, Any}  # (pbi_techs)
    pbi_max_kw::Dict{String, Any}  # (pbi_techs)
    pbi_benefit_per_kwh::Dict{String, Any}  # (pbi_techs)
    boiler_efficiency::Dict{String, <:Real}
    fuel_cost_per_kwh::Dict{String, AbstractArray}  # Fuel cost array for all time_steps
    ghp_options::UnitRange{Int64}  # Range of the number of GHP options
    require_ghp_purchase::Int64  # 0/1 binary if GHP purchase is forced/required
    ghp_heating_thermal_load_served_kw::Array{Float64,2}  # Array of heating load (thermal!) profiles served by GHP
    ghp_cooling_thermal_load_served_kw::Array{Float64,2}  # Array of cooling load profiles served by GHP
    space_heating_thermal_load_reduction_with_ghp_kw::Array{Float64,2}  # Array of heating load reduction (thermal!) profile from GHP retrofit
    cooling_thermal_load_reduction_with_ghp_kw::Array{Float64,2}  # Array of cooling load reduction (thermal!) profile from GHP retrofit
    ghp_electric_consumption_kw::Array{Float64,2}  # Array of electric load profiles consumed by GHP
    ghp_installed_cost::Array{Float64,1}  # Array of installed cost for GHP options
    ghp_om_cost_year_one::Array{Float64,1}  # Array of O&M cost for GHP options    
    tech_renewable_energy_fraction::Dict{String, <:Real} # union(techs.elec, techs.fuel_burning)
    tech_emissions_factors_CO2::Dict{String, <:Real} # (techs)
    tech_emissions_factors_NOx::Dict{String, <:Real} # (techs)
    tech_emissions_factors_SO2::Dict{String, <:Real} # (techs)
    tech_emissions_factors_PM25::Dict{String, <:Real} # (techs)
    techs_operating_reserve_req_fraction::Dict{String, <:Real} # (techs.all)
    heating_cop::Dict{String, Array{<:Real, 1}} # (techs.ashp)
    cooling_cop::Dict{String, Array{<:Real, 1}} # (techs.ashp)
    heating_cf::Dict{String, Array{<:Real, 1}} # (techs.ashp)
    cooling_cf::Dict{String, Array{<:Real, 1}} # (techs.ashp)
    heating_loads_kw::Dict{String, <:Real} # (heating_loads)
    unavailability::Dict{String, Array{Float64,1}}  # Dict by tech of unavailability profile
end
```


`REopt.REoptInputs` — Method



```julia
REoptInputs(fp::String)
```

Use `fp` to load in JSON scenario:


```
function REoptInputs(fp::String)
    s = Scenario(JSON.parsefile(fp))
    REoptInputs(s)
end
```

Useful if you want to manually modify REoptInputs before solving the model.

`REopt.REoptInputs` — Method



```julia
REoptInputs(s::AbstractScenario)
```

Constructor for REoptInputs. Translates the `Scenario` into all the data necessary for building the JuMP model.

## Design Concepts for REoptInputs

At a high level the REoptInputs constructor does the following tasks:

- build index sets for the JuMP model decision variables,
- create maps from one set to another set,
- and generate coefficient arrays necessary for model constraints.

#### Index Sets

There are a few `String[]` that are built by REoptInputs that are then used as index sets in the model constraints. The primary index set is the `techs.all` array of strings, which contains all the technolgy names that are being modeled. With the `techs.all` array we can easily apply a constraint over all technolgies. For example:


```julia
@constraint(m, [t in p.techs.all],
    m[Symbol("dvSize"*_n)][t] <= p.max_sizes[t]
)
```

where `p` is the `REoptInputs` struct. There are a couple things to note from this last example:

- The decision variable `dvSize` is accessed in the JuMP.Model `m` using the `Symbol` notation so that this constraint can be used in the multi-node case in addition to the single node case. The `_n` input value is an empty string by default and in the case of a multi-node model the `_n` string will be set by the `Site.node` integer. For example, if `Site.node` is `3` then `_n` is "_3".
- The `p.max_sizes` array is also indexed on `p.techs.all`. The `max_sizes` is built in the REoptInputs constructor by using all the technologies in the `Scenario` that have `max_kw` values greater than zero.

Besides the `techs.all` array the are many sub-sets, such as `techs.pv`, `techs.gen`, `techs.elec`, `p.techs.segmented`, `techs.no_curtail`, that allow us to apply constraints to those sets. For example:


```julia
for t in p.techs.no_curtail
    for ts in p.time_steps
        fix(m[Symbol("dvCurtail"*_n)][t, ts] , 0.0, force=true)
    end
end
```


#### Set maps

The set maps are best explained with an example. The `techs_by_exportbin` map uses each technology'sattributes (eg. `PV`) to map each technology to which export bins that technology can access. The export bins include:

- `:NEM` (Net Energy Metering)
- `:WHL` (Wholesale)
- `:EXC` (Excess, beyond NEM)

The bins that a technology can access are determined by the technologies attributes `can_net_meter`, `can_wholesale`, and `can_export_beyond_nem_limit`. So if `PV.can_net_meter = true`, `Wind.can_net_meter = true` and all the other attributes are `false` then the `techs_by_exportbin` will only have one non-empty key:


```julia
techs_by_exportbin = Dict(
    :NEM => ["PV", "Wind"],
    :WHL => [],
    :EXC => []
)
```

A use-case example for the `techs_by_exportbin` map is defining the net metering benefit:


```julia
NEM_benefit = @expression(m, p.pwf_e * p.hours_per_time_step *
    sum( sum(p.s.electric_tariff.export_rates[:NEM][ts] * m[Symbol("dvProductionToGrid"*_n)][t, :NEM, ts] 
        for t in p.techs_by_exportbin[:NEM]) for ts in p.time_steps)
)
```

Other set maps include: `export_bins_by_tech` and `n_segs_by_tech`. The latter tells how many cost curve segments each technology has.

#### Coefficient Arrays

The JuMP model costs are formulated in net present value terms, accounting for all benefits (production, capacity, and investment incentives) and the total cost over the `analysis_period`. The `REoptInputs` constructor translates the raw input parameters, such as the operations and maintenance costs, into present value terms using the provided discount rate. For example, the `pwf_e` is the present worth factor for electricity that accounts for the `elec_cost_escalation_rate_fraction`, the `analysis_period`, and the `offtaker_discount_rate_fraction`. Note that tax benefits are applied directly in the JuMP model for clarity on which costs are tax-deductible and which are not.

Besides econimic parameters, the `REoptInputs` constructor also puts together the important `production_factor` array. The `production_factor` array is simple for continuously variable generators (such as the `Generator`), for which the `production_factor` is 1 in all time steps. However, for variable generators (such as `Wind` and `PV`) the `production_factor` varies by time step. If the user does not provide the `PV` production factor, for example, then the `REoptInputs` constructor uses the PVWatts API to download the location specific `PV` production factor. `REoptInputs` also accounts for the `PV.degradation_fraction` in building the `production_factor` array.
