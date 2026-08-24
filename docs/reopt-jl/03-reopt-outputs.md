# Outputs

Source: https://natlabrockies.github.io/REopt.jl/dev/reopt/outputs/

---

# Outputs

## Financial outputs

`REopt.add_financial_results` — Function

`Financial` results keys:

- `lcc` Optimal lifecycle cost
- `lifecycle_generation_tech_capital_costs` LCC component. Net capital costs for all generation technologies, in present value, including replacement costs and incentives. This value does not include offgrid_other_capital_costs.
- `lifecycle_storage_capital_costs` LCC component. Net capital costs for all storage technologies, in present value, including replacement costs and incentives. This value does not include offgrid_other_capital_costs.
- `lifecycle_om_costs_after_tax` LCC component. Present value of all O&M costs, after tax. (does not include fuel costs)
- `lifecycle_fuel_costs_after_tax` LCC component. Present value of all fuel costs over the analysis period, after tax.
- `lifecycle_chp_standby_cost_after_tax` LCC component. Present value of all CHP standby charges, after tax.
- `lifecycle_elecbill_after_tax` LCC component. Present value of all electric utility charges, including compensation for exports, after tax.
- `lifecycle_production_incentive_after_tax` LCC component. Present value of all production-based incentives, after tax.
- `lifecycle_offgrid_other_annual_costs_after_tax` LCC component. Present value of offgrid_other_annual_costs over the analysis period, after tax.
- `lifecycle_offgrid_other_capital_costs` LCC component. Equal to offgrid_other_capital_costs with straight line depreciation applied over analysis period. The depreciation expense is assumed to reduce the owner's taxable income.
- `lifecycle_outage_cost` LCC component. Expected outage cost.
- `lifecycle_MG_upgrade_and_fuel_cost` LCC component. Cost to upgrade generation and storage technologies to be included in microgrid, plus expected microgrid fuel costs, assuming outages occur in first year with specified probabilities.
- `lifecycle_om_costs_before_tax` Present value of all O&M costs, before tax.
- `year_one_total_operating_cost_before_tax` Year one total operating costs, before tax. Includes energy costs, export value, O&M, fuel, and standby costs.
- `year_one_total_operating_cost_after_tax` Year one total operating costs, after tax. Includes energy costs, export value, O&M, fuel, and standby costs.
- `year_one_fuel_cost_before_tax` Year one fuel costs, before tax. Does not include fuel use during outages if using multiple outage modeling.
- `year_one_fuel_cost_after_tax` Year one fuel costs, after tax. Does not include fuel use during outages if using multiple outage modeling.
- `year_one_om_costs_before_tax` Year one O&M costs, before tax.
- `year_one_om_costs_after_tax` Year one O&M costs, after tax.
- `year_one_chp_standby_cost_after_tax` Year one CHP standby costs, after tax.
- `year_one_chp_standby_cost_before_tax` Year one CHP standby costs, before tax.
- `lifecycle_capital_costs_plus_om_after_tax` Capital cost for all technologies plus present value of operations and maintenance over anlaysis period.
- `lifecycle_capital_costs` Net capital costs for all technologies, in present value, including replacement costs and incentives.
- `initial_capital_costs` Up-front capital costs for all technologies, in present value, excluding replacement costs and incentives. If third party ownership, represents cost to third party.
- `initial_capital_costs_after_incentives` Up-front capital costs for all technologies, in present value, excluding replacement costs, and accounting for incentives. Note: the ITC and MACRS are discounted by 1 year, and 1-7 years, respectively, to obtain the present value. If third party ownership, represents cost to third party.
- `replacements_future_cost_after_tax` Future cost of replacing storage and/or generator systems, after tax.
- `replacements_present_cost_after_tax` Present value cost of replacing storage and/or generator systems, after tax.
- `om_and_replacement_present_cost_after_tax` Present value of all O&M and replacement costs, after tax.
- `developer_om_and_replacement_present_cost_after_tax` Present value of all O&M and replacement costs incurred by developer, after tax.
- `offgrid_microgrid_lcoe_dollars_per_kwh` Levelized cost of electricity for modeled off-grid system.
- `lifecycle_emissions_cost_climate` LCC component if Settings input include_climate_in_objective is true. Present value of CO2 emissions cost over the analysis period.
- `lifecycle_emissions_cost_health` LCC component if Settings input include_health_in_objective is true. Present value of NOx, SO2, and PM2.5 emissions cost over the analysis period.

calculated in combine_results function if BAU scenario is run:

- `breakeven_cost_of_emissions_reduction_per_tonne_CO2`

'Series' and 'Annual' energy outputs are average annual

REopt performs load balances using average annual production values for technologies that include degradation. Therefore, all timeseries (`_series`) and `annual_` results should be interpretted as energy outputs averaged over the analysis period.

Two Methods for Simple Payback

REopt Financial outputs include a comprehensive `simple_payback_years` calculation. This is the year in which cumulative net free cashflows become positive. For a third party analysis, the SPP is for the developer. A simplified payback period can also be calculated as: `capital_costs_after_non_discounted_incentives` divided by `year_one_total_operating_cost_savings_after_tax`.

## Financial outputs adders with BAU Scenario

`REopt.combine_results` — Method



```julia
combine_results(bau::Dict, opt::Dict)
```

Combine two results dictionaries into one using BAU and optimal scenario results. New fields added to the Financial output/results:

- `npv`: Net Present Value of the optimal scenario
- `year_one_total_operating_cost_savings_before_tax`: Total operating cost savings in year 1 before tax
- `year_one_total_operating_cost_savings_after_tax`: Total operating cost savings in year 1 after tax
- `breakeven_cost_of_emissions_reduction_per_tonne_CO2`: Breakeven cost of CO2 (usd per tonne) that would yield an npv of 0, holding all other inputs constant
- `lifecycle_emissions_reduction_CO2_fraction`: Fraction of CO2 emissions reduced in the optimal scenario compared to the BAU scenario

## ElectricTariff outputs

`REopt.add_electric_tariff_results` — Method

`ElectricTariff` results keys:

- `lifecycle_energy_cost_after_tax` lifecycle cost of energy from the grid in present value, after tax
- `year_one_energy_cost_before_tax` cost of energy from the grid over the first year, before considering tax benefits
- `lifecycle_demand_cost_after_tax` lifecycle cost of power from the grid in present value, after tax
- `year_one_demand_cost_before_tax` cost of power from the grid over the first year, before considering tax benefits
- `lifecycle_fixed_cost_after_tax` lifecycle fixed cost in present value, after tax
- `year_one_fixed_cost_before_tax` fixed cost over the first year, before considering tax benefits
- `lifecycle_min_charge_adder_after_tax` lifecycle minimum charge in present value, after tax
- `year_one_min_charge_adder_before_tax` minimum charge over the first year, before considering tax benefits
- `year_one_bill_before_tax` sum of `year_one_energy_cost_before_tax`, `year_one_demand_cost_before_tax`, `year_one_fixed_cost_before_tax`, `year_one_min_charge_adder_before_tax`, and `year_one_coincident_peak_cost_before_tax`
- `lifecycle_export_benefit_after_tax` lifecycle export credits in present value, after tax
- `year_one_export_benefit_before_tax` export credits over the first year, before considering tax benefits. A positive value indicates a benefit.
- `lifecycle_coincident_peak_cost_after_tax` lifecycle coincident peak charge in present value, after tax
- `year_one_coincident_peak_cost_before_tax` coincident peak charge over the first year

Outputs related to electric tariff (year-one rates and costs not escalated):

- `monthly_fixed_cost_series_before_tax` the fixed monthly cost of electricity for modeled meter per chosen electric tariff in $/month
- `energy_rate_series` dictionary for cost of electricity, each key corresponds to a tier with value being $/kWh timeseries
- `energy_rate_tier_limits` dictionary for energy rate tier limits, each key corresponds to a tier with value being kWh limit
- `energy_rate_average_series` average energy rate across all tiers as $/kWh timeseries
- `facility_demand_monthly_rate_series` facility demand charge in $/kW/month (keys = tiers, values = demand charge for each month)
- `facility_demand_monthly_rate_tier_limits` facility demand charge limits in kW (keys = tiers, values = demand limit for each month)
- `tou_demand_rate_series` is a dictionary with TOU demand charges in $/kW as timeseries for each timestep
- `demand_rate_average_series` average TOU demand rate across all tiers as $/kW timeseries
- `tou_demand_rate_tier_limits` TOU demand charge limits in kW

Outputs related to REopt calculated costs of electricity (year-one rates and costs not escalated):

- `energy_cost_series_before_tax` timeseries of cost of electricity purchases from the grid (grid to total net load) in $
- `monthly_energy_cost_series_before_tax` Monthly energy costs, summed across all tiers in $
- `monthly_facility_demand_cost_series_before_tax` Monthly facility demand cost, dictionary by Tier number in $/month
- `tou_demand_metrics` -> month: Month this TOU period applies to
- `tou_demand_metrics` -> tier: Tier of TOU period
- `tou_demand_metrics` -> demand_rate: $/kW TOU demand charge
- `tou_demand_metrics` -> measured_tou_peak_demand: measured peak kW load in TOU period in kW
- `tou_demand_metrics` -> demand_charge_before_tax`: calculated demand charge in $
- `monthly_tou_demand_cost_series_before_tax` Monthly TOU demand costs, dictionary by Tier number in $/month
- `monthly_demand_cost_series_before_tax` Monthly total facility plus TOU demand costs, summed across all tiers in $/month

Prefix net_metering, wholesale, or net_metering_excess (export categories) for following outputs, all can be in results if relevant inputs are provided.

- `_export_rate_series` export rate timeseries for type of export category in $/kWh
- `_electric_to_grid_series_kw` exported electricity timeseries for type of export category in kW
- `_monthly_export_series_kwh` monthly exported energy totals by export category in kWh
- `_monthly_export_cost_benefit_before_tax` monthly export benefit by export category in $

Handling of tiered rates

Energy and demand charges costs are returned as a dictionary with each key corresponding to a cost tier. REopt assumes all TOU periods have the same tier limits

## ElectricLoad outputs

`REopt.add_electric_load_results` — Function

`ElectricLoad` results keys:

- `load_series_kw` # vector of BAU site load in every time step. Does not include electric load for any new heating or cooling techs.
- `critical_load_series_kw` # vector of site critical load in every time step
- `annual_calculated_kwh` # sum of the `load_series_kw`. Does not include electric load for any new heating or cooling techs.
- `annual_electric_load_with_thermal_conversions_kwh` # Total end-use electrical load, including electrified heating and cooling end-use load
- `offgrid_load_met_series_kw` # vector of electric load met by generation techs, for off-grid scenarios only
- `offgrid_load_met_fraction` # percentage of total electric load met on an annual basis, for off-grid scenarios only
- `offgrid_annual_oper_res_required_series_kwh` # total operating reserves required (for load and techs) on an annual basis, for off-grid scenarios only
- `offgrid_annual_oper_res_provided_series_kwh` # total operating reserves provided on an annual basis, for off-grid scenarios only
- `monthly_calculated_kwh` # vector of BAU monthly energy consumption at a site
- `monthly_peaks_kw` # vector of BAU monthly peak demand
- `annual_peak_kw` # annual BAU peak electricity demand

'Series' and 'Annual' energy outputs are average annual

REopt performs load balances using average annual production values for technologies that include degradation. Therefore, all timeseries (`_series`) and `annual_` results should be interpretted as energy outputs averaged over the analysis period.

## ElectricUtility outputs

`REopt.add_electric_utility_results` — Method

`ElectricUtility` results keys:

- `annual_energy_supplied_kwh` # Total energy supplied from the grid in an average year.
- `electric_to_load_series_kw` # Vector of power drawn from the grid to serve load.
- `electric_to_storage_series_kw` # Vector of power drawn from the grid to charge the battery.
- `annual_renewable_electricity_supplied_kwh` # Total renewable electricity supplied from the grid in an average year.
- `annual_emissions_tonnes_CO2` # Average annual total tons of CO2 emissions associated with the site's grid-purchased electricity. If include_exported_elec_emissions_in_total is False, this value only reflects grid purchases. Otherwise, it accounts for emissions offset from any export to the grid.
- `annual_emissions_tonnes_NOx` # Average annual total tons of NOx emissions associated with the site's grid-purchased electricity. If include_exported_elec_emissions_in_total is False, this value only reflects grid purchases. Otherwise, it accounts for emissions offset from any export to the grid.
- `annual_emissions_tonnes_SO2` # Average annual total tons of SO2 emissions associated with the site's grid-purchased electricity. If include_exported_elec_emissions_in_total is False, this value only reflects grid purchases. Otherwise, it accounts for emissions offset from any export to the grid.
- `annual_emissions_tonnes_PM25` # Average annual total tons of PM25 emissions associated with the site's grid-purchased electricity. If include_exported_elec_emissions_in_total is False, this value only reflects grid purchsaes. Otherwise, it accounts for emissions offset from any export to the grid.
- `lifecycle_emissions_tonnes_CO2` # Total tons of CO2 emissions associated with the site's grid-purchased electricity over the analysis period. If include_exported_elec_emissions_in_total is False, this value only reflects grid purchaes. Otherwise, it accounts for emissions offset from any export to the grid.
- `lifecycle_emissions_tonnes_NOx` # Total tons of NOx emissions associated with the site's grid-purchased electricity over the analysis period. If include_exported_elec_emissions_in_total is False, this value only reflects grid purchaes. Otherwise, it accounts for emissions offset from any export to the grid.
- `lifecycle_emissions_tonnes_SO2` # Total tons of SO2 emissions associated with the site's grid-purchased electricity over the analysis period. If include_exported_elec_emissions_in_total is False, this value only reflects grid purchaes. Otherwise, it accounts for emissions offset from any export to the grid.
- `lifecycle_emissions_tonnes_PM25` # Total tons of PM2.5 emissions associated with the site's grid-purchased electricity over the analysis period. If include_exported_elec_emissions_in_total is False, this value only reflects grid purchaes. Otherwise, it accounts for emissions offset from any export to the grid.
- `avert_emissions_region` # EPA AVERT region of the site. Used for health-related emissions from grid electricity (populated if default emissions values are used) and climate emissions if "co2_from_avert" is set to true.
- `distance_to_avert_emissions_region_meters` # Distance in meters from the site to the nearest AVERT emissions region.
- `cambium_region` # NLR Cambium region of the site. Used for climate-related emissions from grid electricity (populated only if default (Cambium) climate emissions values are used)

'Series' and 'Annual' energy and emissions outputs are average annual

REopt performs load balances using average annual production values for technologies that include degradation. Therefore, all timeseries (`_series`) and `annual_` results should be interpretted as energy and emissions outputs averaged over the analysis period.

Emissions outputs

By default, REopt uses marginal emissions rates for grid-purchased electricity. Marginal emissions rates are most appropriate for reporting a change in emissions (avoided or increased) rather than emissions totals. It is therefore recommended that emissions results from REopt (using default marginal emissions rates) be reported as the difference in emissions between the optimized and BAU case. Note also that the annual_emissions metrics are average annual emissions over the analysis period, accounting for expected changes in future grid emissions.

## PV outputs

`REopt.add_pv_results` — Method

`PV` results keys:

- `size_kw` Optimal PV DC capacity
- `lifecycle_om_cost_after_tax` Lifecycle operations and maintenance cost in present value, after tax
- `year_one_energy_produced_kwh` Energy produced over the first year
- `annual_energy_produced_kwh` Average annual energy produced, accounting for degradation. Includes curtailed energy.
- `lcoe_per_kwh` Levelized Cost of Energy produced by the PV system
- `electric_to_load_series_kw` Vector of power used to meet load over an average year
- `electric_to_storage_series_kw` Vector of power used to charge the battery over an average year
- `electric_to_grid_series_kw` Vector of power exported to the grid over an average year
- `electric_curtailed_series_kw` Vector of power curtailed over an average year
- `annual_energy_exported_kwh` Average annual energy exported to the grid
- `production_factor_series` PV production factor in each time step, either provided by user or obtained from PVWatts

Warn

The key(s) used to access PV outputs in the results dictionary is determined by the `PV.name` value to allow for modeling multiple PV options. (The default `PV.name` is "PV".)

Existing PV

All outputs account for any existing PV. E.g., `size_kw` includes existing capacity and the REopt-recommended additional capacity.

'Series' and 'Annual' energy outputs are average annual

REopt performs load balances using average annual production values for technologies that include degradation. Therefore, all timeseries (`_series`) and `annual_` results should be interpretted as energy outputs averaged over the analysis period.

## Wind outputs

`REopt.add_wind_results` — Function

`Wind` results keys:

- `size_kw` Optimal Wind capacity [kW]
- `lifecycle_om_cost_after_tax` Lifecycle operations and maintenance cost in present value, after tax
- `year_one_om_cost_before_tax` Operations and maintenance cost in the first year, before tax benefits
- `electric_to_storage_series_kw` Vector of power used to charge the battery over an average year
- `electric_to_grid_series_kw` Vector of power exported to the grid over an average year
- `annual_energy_exported_kwh` Average annual energy exported to the grid
- `electric_to_load_series_kw` Vector of power used to meet load over an average year
- `annual_energy_produced_kwh` Average annual energy produced, accounting for degradation. Includes curtailed energy.
- `lcoe_per_kwh` Levelized Cost of Energy produced by the PV system
- `electric_curtailed_series_kw` Vector of power curtailed over an average year
- `production_factor_series` Wind production factor in each time step, either provided by user or obtained from SAM

'Series' and 'Annual' energy outputs are average annual

REopt performs load balances using average annual production values for technologies that include degradation. Therefore, all timeseries (`_series`) and `annual_` results should be interpretted as energy outputs averaged over the analysis period.

## ElectricStorage outputs

`REopt.add_electric_storage_results` — Method

`ElectricStorage` results keys:

- `size_kw` Optimal inverter capacity
- `size_kwh` Optimal storage capacity
- `soc_series_fraction` Vector of normalized (0-1) state of charge values over an average year
- `storage_to_load_series_kw` Vector of power used to meet load over an average year
- `storage_to_grid_series_kw` Vector of power exported to the grid over an average year
- `initial_capital_cost` Upfront capital cost for storage and inverter

**The following results are reported if storage degradation is modeled:**

- `state_of_health_series_fraction`
- `maintenance_cost`
- `replacement_month` # only applies is maintenance_strategy = "replacement"
- `residual_value`
- `total_residual_kwh` # only applies is maintenance_strategy = "replacement"

'Series' and 'Annual' energy outputs are average annual

REopt performs load balances using average annual production values for technologies that include degradation. Therefore, all timeseries (`_series`) and `annual_` results should be interpretted as energy outputs averaged over the analysis period.

## HotThermalStorage outputs

`REopt.add_hot_storage_results` — Method

`HotThermalStorage` results keys:

- `size_kwh` Optimal TES capacity, by energy [kWh]
- `size_gal` Optimal TES capacity, by volume [gal]
- `soc_series_fraction` Vector of normalized (0-1) state of charge values over an average year [-]
- `storage_to_steamturbine_series_mmbtu_per_hour` Vector of heat sent to steam turbine over an average year [MMBTU/hr]
- `storage_to_absorption_chiller_series_mmbtu_per_hour` Vector of heat sent to absorption chiller over an average year [MMBTU/hr]
- `storage_to_load_series_mmbtu_per_hour` Vector of thermal power used to meet load over an average year [MMBTU/hr]
- `storage_to_space_heating_load_series_mmbtu_per_hour` Vector of heat sent to space heating load over an average year [MMBTU/hr]
- `storage_to_dhw_load_series_mmbtu_per_hour` Vector of heat sent to domestic hot water load over an average year [MMBTU/hr]
- `storage_to_process_heat_load_series_mmbtu_per_hour` Vector of heat sent to process heat load over an average year [MMBTU/hr]

'Series' and 'Annual' energy outputs are average annual

REopt performs load balances using average annual production values for technologies that include degradation. Therefore, all timeseries (`_series`) and `annual_` results should be interpretted as energy outputs averaged over the analysis period.

## HighTempThermalStorage outputs

`REopt.add_high_temp_thermal_storage_results` — Method

`HighTempThermalStorage` results keys:

- `size_kwh` Optimal TES capacity, by energy [kWh]
- `soc_series_fraction` Vector of normalized (0-1) state of charge values over an average year [-]
- `storage_to_steamturbine_series_mmbtu_per_hour` Vector of heat sent to steam turbine over an average year [MMBTU/hr]
- `storage_to_absorption_chiller_series_mmbtu_per_hour` Vector of heat sent to absorption chiller over an average year [MMBTU/hr]
- `storage_to_load_series_mmbtu_per_hour` Vector of thermal power used to meet load over an average year [MMBTU/hr]
- `storage_to_space_heating_load_series_mmbtu_per_hour` Vector of heat sent to space heating load over an average year [MMBTU/hr]
- `storage_to_dhw_load_series_mmbtu_per_hour` Vector of heat sent to domestic hot water load over an average year [MMBTU/hr]
- `storage_to_process_heat_load_series_mmbtu_per_hour` Vector of heat sent to process heat load over an average year [MMBTU/hr]

'Series' and 'Annual' energy outputs are average annual

REopt performs load balances using average annual production values for technologies that include degradation. Therefore, all timeseries (`_series`) and `annual_` results should be interpretted as energy outputs averaged over the analysis period.

## ColdThermalStorage outputs

`REopt.add_cold_storage_results` — Method

`ColdThermalStorage` results:

- `size_gal` Optimal TES capacity, by volume [gal]
- `soc_series_fraction` Vector of normalized (0-1) state of charge values over an average year [-]
- `storage_to_load_series_ton` Vector of power used to meet load over an average year [ton]

## Generator outputs

`REopt.add_generator_results` — Method

`Generator` results keys:

- `size_kw` Optimal generator capacity
- `lifecycle_fixed_om_cost_after_tax` Lifecycle fixed operations and maintenance cost in present value, after tax
- `year_one_fixed_om_cost_before_tax` fixed operations and maintenance cost over the first year, before considering tax benefits
- `lifecycle_variable_om_cost_after_tax` Lifecycle variable operations and maintenance cost in present value, after tax. Includes om_cost_per_kwh and om_cost_per_hr_per_kw_rated
- `year_one_variable_om_cost_before_tax` variable operations and maintenance cost over the first year, before considering tax benefits. Includes om_cost_per_kwh and om_cost_per_hr_per_kw_rated
- `lifecycle_fuel_cost_after_tax` Lifecycle fuel cost in present value, after tax
- `year_one_fuel_cost_before_tax` Fuel cost over the first year, before considering tax benefits. Does not include fuel use during outages if using multiple outage modeling.
- `year_one_fuel_cost_after_tax` Fuel cost over the first year, after considering tax benefits. Does not include fuel use during outages if using multiple outage modeling.
- `annual_fuel_consumption_gal` Gallons of fuel used in each year
- `electric_to_storage_series_kw` Vector of power sent to battery in an average year
- `electric_to_grid_series_kw` Vector of power sent to grid in an average year
- `electric_to_load_series_kw` Vector of power sent to load in an average year
- `annual_energy_produced_kwh` Average annual energy produced over analysis period

'Series' and 'Annual' energy outputs are average annual

REopt performs load balances using average annual production values for technologies that include degradation. Therefore, all timeseries (`_series`) and `annual_` results should be interpretted as energy outputs averaged over the analysis period.

## ExistingBoiler outputs

`REopt.add_existing_boiler_results` — Function

`ExistingBoiler` results keys:

- `size_mmbtu_per_hour` # Thermal production capacity size of the Boiler [MMBtu/hr]
- `fuel_consumption_series_mmbtu_per_hour` # Fuel consumption series [MMBtu/hr]
- `annual_fuel_consumption_mmbtu` # Fuel consumed in a year [MMBtu]
- `thermal_production_series_mmbtu_per_hour` # Thermal energy production series [MMBtu/hr]
- `annual_thermal_production_mmbtu` # Thermal power production in a year [MMBtu]
- `thermal_to_storage_series_mmbtu_per_hour` # Thermal power production to TES (HotThermalStorage) series [MMBtu/hr]
- `thermal_to_steamturbine_series_mmbtu_per_hour` # Thermal power production to SteamTurbine series [MMBtu/hr]
- `thermal_to_load_series_mmbtu_per_hour` # Thermal power production to serve the heating load series [MMBtu/hr] (superset of "to_absorption_chiller", "to_space_heating_load", "to_dhw_load", and "to_process_heat_load")
- `thermal_to_absorption_chiller_series_mmbtu_per_hour` # Thermal power production to serve absorption chiller load series [MMBtu/hr]
- `thermal_to_dhw_load_series_mmbtu_per_hour` # Thermal power production to serve domestic hot water load series [MMBtu/hr]
- `thermal_to_space_heating_load_series_mmbtu_per_hour` # Thermal power production to serve space heating load series [MMBtu/hr]
- `thermal_to_process_heat_load_series_mmbtu_per_hour` # Thermal power production to serve process heat load series [MMBtu/hr]
- `lifecycle_fuel_cost_after_tax` # Life cycle fuel cost [$]
- `year_one_fuel_cost_before_tax` # Year one fuel cost, before tax [$]
- `year_one_fuel_cost_after_tax` # Year one fuel cost, after tax [$]

'Series' and 'Annual' energy outputs are average annual

REopt performs load balances using average annual production values for technologies that include degradation. Therefore, all timeseries (`_series`) and `annual_` results should be interpretted as energy outputs averaged over the analysis period.

## CHP outputs

`REopt.add_chp_results` — Function

`CHP` results keys:

- `size_kw` Power capacity size of the CHP system [kW]
- `size_supplemental_firing_kw` Power capacity of CHP supplementary firing system [kW]
- `annual_fuel_consumption_mmbtu` Fuel consumed in a year [MMBtu]
- `annual_electric_production_kwh` Electric energy produced in a year [kWh]
- `annual_thermal_production_mmbtu` Thermal energy produced in a year (not including curtailed thermal) [MMBtu]
- `annual_thermal_curtailed_mmbtu` Thermal energy curtailed in a year [MMBtu]
- `electric_production_series_kw` Electric power production time-series array [kW]
- `electric_to_grid_series_kw` Electric power exported time-series array [kW]
- `electric_to_storage_series_kw` Electric power to charge the battery storage time-series array [kW]
- `electric_to_load_series_kw` Electric power to serve the electric load time-series array [kW]
- `thermal_to_storage_series_mmbtu_per_hour` Thermal power to TES (HotThermalStorage) time-series array [MMBtu/hr]
- `thermal_curtailed_series_mmbtu_per_hour` Thermal power wasted/unused/vented time-series array [MMBtu/hr]
- `thermal_to_steamturbine_series_mmbtu_per_hour` Thermal (steam) power to steam turbine time-series array [MMBtu/hr]
- `thermal_to_load_series_mmbtu_per_hour` Thermal power to serve the heating load time-series array [MMBtu/hr] (superset of "to_absorption_chiller", "to_space_heating_load", "to_dhw_load", and "to_process_heat_load")
- `thermal_to_absorption_chiller_series_mmbtu_per_hour` Thermal power to serve absorption chiller load [MMBtu/hr]
- `thermal_to_dhw_load_series_mmbtu_per_hour` Thermal power to serve domestic hot water load [MMBtu/hr]
- `thermal_to_space_heating_load_series_mmbtu_per_hour` Thermal power to serve space heating load [MMBtu/hr]
- `thermal_to_process_heat_load_series_mmbtu_per_hour` Thermal power to serve process heat load [MMBtu/hr]
- `year_one_fuel_cost_before_tax` Cost of fuel consumed by the CHP system in year one, before tax [$]
- `year_one_fuel_cost_after_tax` Cost of fuel consumed by the CHP system in year one, after tax
- `lifecycle_fuel_cost_after_tax` Present value of cost of fuel consumed by the CHP system, after tax [$]
- `year_one_standby_cost_before_tax` CHP standby charges in year one, before tax [$]
- `year_one_standby_cost_after_tax` CHP standby charges in year one, after tax
- `lifecycle_standby_cost_after_tax` Present value of all CHP standby charges, after tax.
- `thermal_production_series_mmbtu_per_hour`
- `initial_capital_costs` Initial capital costs of the CHP system, before incentives [$]

'Series' and 'Annual' energy outputs are average annual

REopt performs load balances using average annual production values for technologies that include degradation. Therefore, all timeseries (`_series`) and `annual_` results should be interpretted as energy outputs averaged over the analysis period.

## Boiler outputs

`REopt.add_boiler_results` — Function

`Boiler` results keys:

- `size_mmbtu_per_hour` # Thermal production capacity size of the Boiler [MMBtu/hr]
- `fuel_consumption_series_mmbtu_per_hour` # Fuel consumption series [MMBtu/hr]
- `annual_fuel_consumption_mmbtu` # Fuel consumed in a year [MMBtu]
- `thermal_production_series_mmbtu_per_hour` # Thermal energy production series [MMBtu/hr]
- `annual_thermal_production_mmbtu` # Thermal energy produced in a year [MMBtu]
- `thermal_to_storage_series_mmbtu_per_hour` # Thermal power production to TES (HotThermalStorage) series [MMBtu/hr]
- `thermal_to_steamturbine_series_mmbtu_per_hour` # Thermal power production to SteamTurbine series [MMBtu/hr]
- `thermal_to_load_series_mmbtu_per_hour` # Thermal power production to serve the heating load series [MMBtu/hr] (superset of "to_absorption_chiller", "to_space_heating_load", "to_dhw_load", and "to_process_heat_load")
- `thermal_to_absorption_chiller_series_mmbtu_per_hour` # Thermal power production to serve absorption chiller load series [MMBtu/hr]
- `thermal_to_dhw_load_series_mmbtu_per_hour` # Thermal power production to serve domestic hot water load series [MMBtu/hr]
- `thermal_to_space_heating_load_series_mmbtu_per_hour` # Thermal power production to serve space heating load series [MMBtu/hr]
- `thermal_to_process_heat_load_series_mmbtu_per_hour` # Thermal power production to serve process heat load series [MMBtu/hr]
- `lifecycle_fuel_cost_after_tax` # Life cycle fuel cost [$]
- `year_one_fuel_cost_before_tax` # Year one fuel cost, before tax [$]
- `year_one_fuel_cost_after_tax` # Year one fuel cost, after tax [$]
- `lifecycle_per_unit_prod_om_costs` # Life cycle production-based O&M cost [$]

'Series' and 'Annual' energy outputs are average annual

REopt performs load balances using average annual production values for technologies that include degradation. Therefore, all timeseries (`_series`) and `annual_` results should be interpretted as energy outputs averaged over the analysis period.

## HeatingLoad outputs

`REopt.add_heating_load_results` — Function

`HeatingLoad` results keys:

- `dhw_thermal_load_series_mmbtu_per_hour` vector of site thermal domestic hot water load in every time step
- `space_heating_thermal_load_series_mmbtu_per_hour` vector of site thermal space heating load in every time step
- `process_heat_thermal_load_series_mmbtu_per_hour` vector of site thermal process heat load in every time step
- `total_heating_thermal_load_series_mmbtu_per_hour` vector of sum thermal heating load in every time step
- `dhw_boiler_fuel_load_series_mmbtu_per_hour` vector of site fuel domestic hot water load in every time step
- `space_heating_boiler_fuel_load_series_mmbtu_per_hour` vector of site fuel space heating load in every time step
- `process_heat_boiler_fuel_load_series_mmbtu_per_hour` vector of site fuel process heat load in every time step
- `total_heating_thermal_load_series_mmbtu_per_hour` vector of sum fuel heating load in every time step
- `annual_calculated_dhw_thermal_load_mmbtu` sum of the `dhw_thermal_load_series_mmbtu_per_hour`
- `annual_calculated_space_heating_thermal_load_mmbtu` sum of the `space_heating_thermal_load_series_mmbtu_per_hour`
- `annual_calculated_process_heat_thermal_load_mmbtu` sum of the `process_heat_thermal_load_series_mmbtu_per_hour`
- `annual_calculated_total_heating_thermal_load_mmbtu` sum of the `total_heating_thermal_load_series_mmbtu_per_hour`
- `annual_calculated_dhw_boiler_fuel_load_mmbtu` sum of the `dhw_boiler_fuel_load_series_mmbtu_per_hour`
- `annual_calculated_space_heating_boiler_fuel_load_mmbtu` sum of the `space_heating_boiler_fuel_load_series_mmbtu_per_hour`
- `annual_calculated_process_heat_boiler_fuel_load_mmbtu` sum of the `process_heat_boiler_fuel_load_series_mmbtu_per_hour`
- `annual_calculated_total_heating_boiler_fuel_load_mmbtu` sum of the `total_heating_boiler_fuel_load_series_mmbtu_per_hour`

## CoolingLoad outputs

`REopt.add_cooling_load_results` — Function

`CoolingLoad` results keys:

- `load_series_ton` # vector of site cooling load in every time step
- `annual_calculated_tonhour` # sum of the `load_series_ton`. Annual site total cooling load [tonhr]
- `electric_chiller_base_load_series_kw` # Hourly total base load drawn from chiller [kW-electric]
- `annual_electric_chiller_base_load_kwh` # Annual total base load drawn from chiller [kWh-electric]

'Series' and 'Annual' energy outputs are average annual

REopt performs load balances using average annual production values for technologies that include degradation. Therefore, all timeseries (`_series`) and `annual_` results should be interpretted as energy outputs averaged over the analysis period.

## Outages outputs

`REopt.add_outage_results` — Function

`Outages` results keys:

- `expected_outage_cost` The expected outage cost over the random outages modeled.
- `max_outage_cost_per_outage_duration` The maximum outage cost in every outage duration modeled.
- `unserved_load_series_kw` The amount of unserved load in each outage and each time step.
- `unserved_load_per_outage_kwh` The total unserved load in each outage.
- `storage_microgrid_upgrade_cost` The cost to include the storage system in the microgrid.
- `storage_discharge_series_kw` Array of storage power discharged in every outage modeled.
- `pv_microgrid_size_kw` Optimal microgrid PV capacity. Note that the name `PV` can change based on user provided `PV.name`.
- `pv_microgrid_upgrade_cost` The cost to include the PV system in the microgrid.
- `pv_to_storage_series_kw` Array of PV power sent to the battery in every outage modeled.
- `pv_curtailed_series_kw` Array of PV curtailed in every outage modeled.
- `pv_to_load_series_kw` Array of PV power used to meet load in every outage modeled.
- `wind_microgrid_size_kw` Optimal microgrid Wind capacity.
- `wind_microgrid_upgrade_cost` The cost to include the Wind system in the microgrid.
- `wind_to_storage_series_kw` Array of Wind power sent to the battery in every outage modeled.
- `wind_curtailed_series_kw` Array of Wind curtailed in every outage modeled.
- `wind_to_load_series_kw` Array of Wind power used to meet load in every outage modeled.
- `generator_microgrid_size_kw` Optimal microgrid Generator capacity. Note that the name `Generator` can change based on user provided `Generator.name`.
- `generator_microgrid_upgrade_cost` The cost to include the Generator system in the microgrid.
- `generator_to_storage_series_kw` Array of Generator power sent to the battery in every outage modeled.
- `generator_curtailed_series_kw` Array of Generator curtailed in every outage modeled.
- `generator_to_load_series_kw` Array of Generator power used to meet load in every outage modeled.
- `generator_fuel_used_per_outage_gal` Array of fuel used in every outage modeled, summed over all Generators.
- `chp_microgrid_size_kw` Optimal microgrid CHP capacity.
- `chp_microgrid_upgrade_cost` The cost to include the CHP system in the microgrid.
- `chp_to_storage_series_kw` Array of CHP power sent to the battery in every outage modeled.
- `chp_curtailed_series_kw` Array of CHP curtailed in every outage modeled.
- `chp_to_load_series_kw` Array of CHP power used to meet load in every outage modeled.
- `chp_fuel_used_per_outage_mmbtu` Array of fuel used in every outage modeled, summed over all CHPs.
- `microgrid_upgrade_capital_cost` Total capital cost of including technologies in the microgrid
- `critical_loads_per_outage_series_kw` Critical load series in every outage modeled
- `soc_series_fraction` ElectricStorage state of charge series in every outage modeled

Warn

The output keys for `Outages` are subject to change.

Note

This `Outages` section is only added to results when outages are modeled via the `ElectricUtility.outage_start_time_steps` and `ElectricUtility.outage_durations` inputs. If the single outage model is used, the outage is included in all time series outputs. See `ElectricUtility` for an explanation of these outage modeling options.

Warn

The `Outages` results can be very large when many outages are modeled and can take a long time to generate.

Accessing outage results

Outage timeseries results are 3-dimensional arrays with dimensions corresponding to the outage durations, the outage start time, and the time step in the outage. For example, `results["Outages"]["pv_to_load_series_kw"][s,t,ts]` is the PV power used to meet load in outage scenario (duration) `s`, starting at time step `t`, at time step `ts` in that outage.

## AbsorptionChiller outputs

`REopt.add_absorption_chiller_results` — Function

`AbsorptionChiller` results keys:

- `size_kw` # Optimal power capacity size of the absorption chiller system [kW]
- `size_ton`
- `thermal_to_storage_series_ton` # Thermal production to ColdThermalStorage
- `thermal_to_load_series_ton` # Thermal production to cooling load
- `thermal_consumption_series_mmbtu_per_hour`
- `annual_thermal_consumption_mmbtu`
- `annual_thermal_production_tonhour`
- `electric_consumption_series_kw`
- `annual_electric_consumption_kwh`

## FlexibleHVAC outputs

`REopt.add_flexible_hvac_results` — Function

`FlexibleHVAC` results keys:

- `purchased`
- `temperatures_degC_node_by_time`
- `upgrade_cost`

## SteamTurbine outputs

`REopt.add_steam_turbine_results` — Function

`SteamTurbine` results keys:

- `size_kw` Power capacity size [kW]
- `annual_thermal_consumption_mmbtu` Thermal (steam) consumption [MMBtu]
- `annual_electric_production_kwh` Electric energy produced in a year [kWh]
- `annual_thermal_production_mmbtu` Thermal energy produced in a year [MMBtu]
- `thermal_consumption_series_mmbtu_per_hour` Thermal (steam) energy consumption series [MMBtu/hr]
- `electric_production_series_kw` Electric power production series [kW]
- `electric_to_grid_series_kw` Electric power exported to grid series [kW]
- `electric_to_storage_series_kw` Electric power to charge the battery series [kW]
- `electric_to_load_series_kw` Electric power to serve load series [kW]
- `thermal_to_storage_series_mmbtu_per_hour` Thermal production to charge the HotThermalStorage series [MMBtu/hr]
- `thermal_to_high_temp_thermal_storage_series_mmbtu_per_hour`
- `thermal_to_load_series_mmbtu_per_hour` Thermal power to serve the heating load time-series array [MMBtu/hr] (superset of "to_absorption_chiller", "to_space_heating_load", "to_dhw_load", and "to_process_heat_load")
- `thermal_to_absorption_chiller_series_mmbtu_per_hour`
- `thermal_to_dhw_load_series_mmbtu_per_hour` Thermal power to serve domestic hot water load [MMBtu/hr]
- `thermal_to_space_heating_load_series_mmbtu_per_hour` Thermal power to serve space heating load [MMBtu/hr]
- `thermal_to_process_heat_load_series_mmbtu_per_hour` Thermal power to serve process heat load [MMBtu/hr]

'Series' and 'Annual' energy outputs are average annual

REopt performs load balances using average annual production values for technologies that include degradation. Therefore, all timeseries (`_series`) and `annual_` results should be interpretted as energy outputs averaged over the analysis period.

## CST outputs

`REopt.add_concentrating_solar_results` — Function

`CST` results keys:

- `size_kw` # Thermal production capacity size of the CST [kW]
- `size_mmbtu_per_hour`` Thermal production capacity size of the CST [MMBtu/hr]
- `electric_consumption_series_kw` # Fuel consumption series [kW]
- `annual_electric_consumption_kwh` # Fuel consumed in a year [kWh]
- `thermal_production_series_mmbtu_per_hour` # Thermal energy production series [MMBtu/hr]
- `annual_thermal_production_mmbtu` # Thermal energy produced in a year [MMBtu]
- `thermal_to_storage_series_mmbtu_per_hour` # Thermal power production to TES (HotThermalStorage) series [MMBtu/hr]
- `thermal_to_high_temp_thermal_storage_series_mmbtu_per_hour` # Thermal power production to TES (HotThermalStorage) series [MMBtu/hr]
- `thermal_to_steamturbine_series_mmbtu_per_hour` # Thermal power production to SteamTurbine series [MMBtu/hr]
- `thermal_curtailed_series_mmbtu_per_hour` Thermal power wasted/unused/vented time-series array [MMBtu/hr]
- `thermal_to_load_series_mmbtu_per_hour` # Thermal power production to serve the heating load series [MMBtu/hr] (superset of "to_absorption_chiller", "to_space_heating_load", "to_dhw_load", and "to_process_heat_load")
- `thermal_to_absorption_chiller_series_mmbtu_per_hour` # Thermal power production to serve absorption chiller load series [MMBtu/hr]
- `thermal_to_dhw_load_series_mmbtu_per_hour` # Thermal power production to serve domestic hot water load series [MMBtu/hr]
- `thermal_to_space_heating_load_series_mmbtu_per_hour` # Thermal power production to serve space heating load series [MMBtu/hr]
- `thermal_to_process_heat_load_series_mmbtu_per_hour` # Thermal power production to serve process heat load series [MMBtu/hr]

'Series' and 'Annual' energy outputs are average annual

REopt performs load balances using average annual production values for technologies that include degradation. Therefore, all timeseries (`_series`) and `annual_` results should be interpretted as energy outputs averaged over the analysis period.
