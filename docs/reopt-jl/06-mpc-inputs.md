# Inputs

Source: https://natlabrockies.github.io/REopt.jl/dev/mpc/inputs/

---

# Inputs

The input structure for MPC models is very similar to the structure for REopt Inputs. The primary differences are

- The MPCElectricTariff requires specifying individual rate components (and does not parse URDB rates like ElectricTariff).
- The capacities of any provided DER must be provided
- The load profile for each time step must be provided

Just like REopt Inputs, inputs to `run_mpc` can be provided in one of three formats:

- a file path (string) to a JSON file,
- a `Dict`, or
- using the `MPCInputs` struct

The accepted keys for the JSON file or `Dict` are:

- ElectricLoad
- ElectricTariff
- PV
- ElectricStorage
- Financial
- Generator
- ElectricUtility
- Settings

The simplest scenario does not have any dispatch optimization and is essentially a cost "calculator":


```javascript
{
    "ElectricLoad": {
        "loads_kw": [10.0, 11.0, 12.0]
    },
    "ElectricTariff": {
        "energy_rates": [0.1, 0.2, 0.3]
    }
}
```


Note

The `ElectricLoad.loads_kw` can have an arbitrary length, but its length must be the same lengths as many other inputs such as the `MPCElectricTariff.energy_rates` and the `PV.production_factor_series`.

Note

Net metering or net billing (wholesale) can be applied in MPC in the same manner they are applied in a typical REopt run. To utilize net metering in MPC, set `ElectricUtility.net_metering_limit_kw` > 0, and specify which MPC techs can_net_meter. Note that MPC will choose between the NEM and WHL bins for each horizon iteration, if both NEM and WHL are available.

Here is a more complex `MPCScenario`, which is used in Examples:


```javascript
{
    "PV": {
        "size_kw": 150,
        "production_factor_series": [
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.05,
            0.10,
            0.15,
            0.30,
            0.6,
            0.5,
            0.3,
            0.02,
            0.01,
            0.005,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0
        ],
        "can_net_meter": false
    },
    "ElectricStorage": {
        "size_kw": 30.0,
        "size_kwh": 60.0,
        "can_grid_charge": true
    },
    "ElectricLoad": {
        "loads_kw": [
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100
        ]
    },
    "ElectricTariff": {
        "energy_rates": [
            0.1,
            0.1,
            0.1,
            0.1,
            0.1,
            0.1,
            0.15,
            0.15,
            0.15,
            0.15,
            0.15,
            0.15,
            0.15,
            0.2,
            0.2,
            0.2,
            0.3,
            0.2,
            0.2,
            0.2,
            0.1,
            0.1,
            0.1,
            0.1
        ],
        "monthly_demand_rates": [10.0],
        "monthly_previous_peak_demands": [98.0],
        "tou_demand_rates": [0.0, 15.0],
        "tou_demand_time_steps": [
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15], 
            [16, 17, 18, 19, 20, 21, 22, 23, 24]
        ],
        "tou_previous_peak_demands": [98.0, 97.0],
        "wholesale_rate": [0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 
            0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05]
    },
    "ElectricUtility" : {
        "net_metering_limit_kw": 0.0
    }
}
```


# MPC Input Structures

Note that the keys of the input `Dict` or JSON file do not need the `MPC` prefix.

## MPCElectricTariff

`REopt.MPCElectricTariff` — Method



```julia
MPCElectricTariff(d::Dict)
```

function for parsing user inputs into


```julia
    struct MPCElectricTariff
        monthly_previous_peak_demands::Array{Float64,1}
        energy_rates::Array{Float64,1} 

        monthly_demand_rates::Array{Float64,1}
        time_steps_monthly::Array{Array{Int64,1},1}  # length = 0 or 12

        tou_demand_rates::Array{Float64,1}
        tou_demand_ratchet_time_steps::Array{Array{Int64,1},1}  # length = n_tou_demand_ratchets
        tou_previous_peak_demands::Array{Float64,1}

        fixed_monthly_charge::Float64
        annual_min_charge::Float64
        min_monthly_charge::Float64

        export_rates::DenseAxisArray{Array{Float64,1}}
        export_bins::Array{Symbol,1}
    end
```

Keys for `d` include:

- `energy_rates`
  - REQUIRED
  - must have length equal to `ElectricLoad.loads_kw`
- `monthly_demand_rates`
  - default = [0]
- `time_steps_monthly`
  - array of arrays for integer time steps that the `monthly_demand_rates` apply to
  - default = [collect(1:length(energy_rates))]
- `monthly_previous_peak_demands`
  - default = [0]
- `tou_demand_rates`
  - an array of time-of-use demand rates
  - must have length equal to `tou_demand_time_steps`
  - default = []
- `tou_demand_time_steps`
  - an array of arrays for the integer time steps that apply to the `tou_demand_rates`
  - default = []
- `tou_previous_peak_demands`
  - an array of the previous peak demands set in each time-of-use demand period
  - must have length equal to `tou_demand_time_steps`
  - default = []
- `net_metering`
  - boolean, if `true` then customer DER export is compensated at the `energy_rates`
- `wholesale_rate`
  - can be a <:Real or Array{<:Real, 1}, or not provided
  - if provided, customer DER export is compensated at the `wholesale_rate`

NOTE: if both `net_metering=true` and `wholesale_rate` are provided then the model can choose from either option.

`net_metering` is passed in from the `MPCScenario` constructor based on `ElectricUtility.net_metering_limit_kw > 0` (mirroring how `src/core` determines the `NEM` export bin).

## MPCElectricLoad

`REopt.MPCElectricLoad` — Type



```julia
MPCElectricLoad

Base.@kwdef struct MPCElectricLoad
    loads_kw::Array{Real,1}
    critical_loads_kw::Union{Nothing, Array{Real,1}} = nothing
end
```


## MPCElectricStorage

`REopt.MPCElectricStorage` — Type



```julia
MPCElectricStorage
```


```julia
Base.@kwdef struct MPCElectricStorage <: AbstractElectricStorage
    size_kw::Float64
    size_kwh::Float64
    charge_efficiency::Float64 =  0.96 * 0.975^0.5
    discharge_efficiency::Float64 =  0.96 * 0.975^0.5
    soc_min_fraction::Float64 = 0.2
    soc_init_fraction::Float64 = 0.5
    can_grid_charge::Bool = true
    can_net_meter::Bool = false
    can_wholesale::Bool = false
    grid_charge_efficiency::Float64 = can_grid_charge ? charge_efficiency : 0.0
    fixed_soc_series_fraction::Union{Nothing, Array{<:Real,1}} = nothing
    fixed_soc_series_fraction_tolerance::Union{Nothing, Real} = !isnothing(fixed_soc_series_fraction) ? 0.02 : nothing
end
```


## MPCFinancial

`REopt.MPCFinancial` — Type



```julia
MPCFinancial

Base.@kwdef struct MPCFinancial
    value_of_lost_load_per_kwh::Union{Array{R,1}, R} where R<:Real = 1.00
end
```


## MPCPV

`REopt.MPCPV` — Type



```julia
MPCPV
```


```julia
Base.@kwdef struct MPCPV
    name::String="PV"
    size_kw::Real = 0
    production_factor_series::Union{Nothing, Array{Real,1}} = nothing # production factor DOES NOT get levelized in MPC. 
end
```


## MPCGenerator

`REopt.MPCGenerator` — Type



```julia
MPCGenerator
```

struct with inner constructor:


```julia
function MPCGenerator(;
    size_kw::Real,
    fuel_cost_per_gallon::Real = 3.0,
    electric_efficiency_full_load::Real = 0.3233,
    electric_efficiency_half_load::Real = electric_efficiency_full_load,
    fuel_avail_gal::Real = 1.0e9,
    fuel_higher_heating_value_kwh_per_gal::Real = KWH_PER_GAL_DIESEL,
    min_turn_down_fraction::Real = 0.0,  # TODO change this to non-zero value
    only_runs_during_grid_outage::Bool = true,
    sells_energy_back_to_grid::Bool = false,
    om_cost_per_kwh::Real=0.0,
    om_cost_per_hr_per_kw_rated::Real=0.0,
    )
```


## MPCSettings

The MPCSettings is the same as the Settings.

## MPCLimits

`REopt.MPCLimits` — Type



```julia
MPCLimits
```

struct for MPC specific input parameters:

- `grid_draw_limit_kw_by_time_step::Vector{<:Real}` limits for grid power consumption in each time step; length must be same as `length(loads_kw)`.
- `export_limit_kw_by_time_step::Vector{<:Real}` limits for grid power export in each time step; length must be same as `length(loads_kw)`.

Warn

`grid_draw_limit_kw_by_time_step` and `export_limit_kw_by_time_step` values can lead to infeasible problems. For example, there is a constraint that the electric load must be met in each time step and by limiting the amount of power from the grid the load balance constraint could be infeasible.
