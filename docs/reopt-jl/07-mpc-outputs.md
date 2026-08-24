# Outputs

Source: https://natlabrockies.github.io/REopt.jl/dev/mpc/outputs/

---

# Outputs

`REopt.mpc_results` — Function

MPC Scenarios will return a results Dict with the following keys:

- `ElectricStorage`
- `HotThermalStorage`
- `ColdThermalStorage`
- `ElectricTariff`
- `ElectricUtility`
- `PV`
- `Generator`

## MPC ElectricStorage outputs

`REopt.add_electric_storage_results` — Method

MPC `ElectricStorage` results keys:

- `soc_series_fraction` Vector of normalized (0-1) state of charge values over time horizon
- `storage_to_load_series_kw` Vector of power used to meet load
- `storage_to_grid_series_kw` Vector of power exported to the grid

## MPC HotThermalStorage outputs

`REopt.add_hot_storage_results` — Method

MPC `HotThermalStorage` results keys:

- `soc_series_fraction` Vector of normalized (0-1) state of charge values over the time horizon [-]

## MPC ColdThermalStorage outputs

`REopt.add_cold_storage_results` — Method

MPC `ColdThermalStorage` results keys:

- `soc_series_fraction` Vector of normalized (0-1) state of charge values over the time horizon [-]

## MPC ElectricTariff outputs

`REopt.add_electric_tariff_results` — Method

MPC `ElectricTariff` results keys:

- `energy_cost`
- `demand_cost`
- `export_benefit`

Prefix net_metering or wholesale (export categories) for following outputs, included when export bins are active:

- `_export_rate_series` export rate timeseries for type of export category in $/kWh (negative values for site compensation for export)
- `_electric_to_grid_series_kw` exported electricity timeseries for type of export category in kW

## MPC ElectricUtility outputs

`REopt.add_electric_utility_results` — Method

MPC `ElectricUtility` results keys:

- `energy_supplied_kwh`
- `electric_to_storage_series_kw`
- `electric_to_load_series_kw`

## MPC PV outputs

`REopt.add_pv_results` — Method

MPC `PV` results keys:

- `electric_to_storage_series_kw`
- `electric_to_grid_series_kw`
- `electric_curtailed_series_kw`
- `electric_to_load_series_kw`
- `energy_produced_kwh`

## MPC Generator outputs

`REopt.add_generator_results` — Method

MPC `Generator` results keys:

- `variable_om_cost`
- `fuel_cost`
- `electric_to_battery_series_kw`
- `electric_to_grid_series_kw`
- `electric_to_load_series_kw`
- `annual_fuel_consumption_gal`
- `energy_produced_kwh`
