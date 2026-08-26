"""Fleet editor: N fuel-fired units and N batteries in the Streamlit form.

Deliberately inert at N = 1. The count control defaults to 1, and at 1 the app
passes `fuel_techs=None` / `storages=None`, which is the single-slot shape the
model has always taken. Nothing on the default path changes, so the validated
suites cannot move -- that is the same gating rule used for operating reserve
and off-grid CHP.

Extra units are additions to the panel's own values: unit 1 is the panel, units
2..N override only what the user changes.
"""

import io
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(BASE, "streamlit_app.py")
s = io.open(P, encoding="utf-8").read()


def sub(old, new, what):
    global s
    if old not in s:
        raise SystemExit("NOT FOUND: " + what)
    s = s.replace(old, new, 1)
    print("  ok  " + what)


# ---------------------------------------------------------------- battery
sub(
    '''            bat_cfg["can_grid_charge"] = st.selectbox(
                "Allow grid to charge battery", [True, False],
                format_func=lambda b: "Yes" if b else "No", key="bat_gridchg",
            ) is True
''',
    '''            bat_cfg["can_grid_charge"] = st.selectbox(
                "Allow grid to charge battery", [True, False],
                format_func=lambda b: "Yes" if b else "No", key="bat_gridchg",
            ) is True

    # ---- optional bank of several batteries -------------------------------
    # REopt.jl indexes storage by name (StorageTypes.elec is a Vector,
    # storage.jl:15); the web form exposes one. At 1 unit nothing changes.
    n_bat = int(st.number_input(
        "Number of battery units", min_value=1, max_value=6, value=1, step=1,
        key="n_bat",
        help="Each unit is sized and dispatched separately with its own prices, "
             "duration limits and round-trip efficiency. Leave at 1 to match the "
             "REopt web form exactly.",
    ))
    if n_bat > 1:
        with st.expander(f"Battery bank — {n_bat} units", expanded=True):
            st.caption(
                "Unit 1 uses the values above. Set each further unit here; the "
                "optimizer sizes every unit independently within its own bounds."
            )
            for _b in range(1, n_bat):
                st.markdown(f"**Battery {_b + 1}**")
                q1, q2, q3, q4 = st.columns(4)
                with q1:
                    st.text_input("Name", value=f"Battery {_b + 1}", key=f"bat{_b}_name")
                    st.number_input("Energy capacity cost ($/kWh)", min_value=0.0,
                                    value=float(bat_cfg["installed_cost_per_kwh"]),
                                    step=5.0, key=f"bat{_b}_kwh_cost")
                with q2:
                    st.number_input("Power capacity cost ($/kW)", min_value=0.0,
                                    value=float(bat_cfg["installed_cost_per_kw"]),
                                    step=5.0, key=f"bat{_b}_kw_cost")
                    st.number_input("Constant cost ($)", min_value=0.0, value=0.0,
                                    step=1000.0, key=f"bat{_b}_const")
                with q3:
                    st.number_input("Minimum energy capacity (kWh)", min_value=0.0,
                                    value=0.0, step=10.0, key=f"bat{_b}_min_kwh")
                    st.number_input("Maximum energy capacity (kWh)", min_value=0.0,
                                    value=1_000_000.0, step=100.0, key=f"bat{_b}_max_kwh")
                with q4:
                    st.number_input("Minimum duration (hours)", min_value=0.0,
                                    value=0.0, step=0.5, key=f"bat{_b}_min_dur")
                    st.number_input("Maximum duration (hours)", min_value=0.0,
                                    value=100000.0, step=0.5, key=f"bat{_b}_max_dur")
else:
    n_bat = 1
''',
    "battery count and bank editor",
)

# ------------------------------------------------------------- fuel fleet
sub(
    """            gen_cfg["replacement_year"] = int(gd["replacement_year"])
            gen_cfg["replace_cost_per_kw"] = float(gd["replace_cost_per_kw"])
""",
    """            gen_cfg["replacement_year"] = int(gd["replacement_year"])
            gen_cfg["replace_cost_per_kw"] = float(gd["replace_cost_per_kw"])

    # ---- part-load curve and turndown, both REopt fields we now honour -----
    with st.expander("Part-load behaviour", expanded=False):
        st.caption(
            "REopt derives an affine fuel curve `fuel = intercept·on + slope·P` "
            "from two efficiency points (utils.jl:645, generator_constraints.jl:8). "
            "Leaving half-load equal to full-load — REopt's own default — makes the "
            "intercept exactly zero and the curve exactly linear, which is what this "
            "calculator has always assumed."
        )
        h1, h2 = st.columns(2)
        with h1:
            _same = st.checkbox(
                "Half-load efficiency equals full-load (REopt default)",
                value=True, key="gen_half_same")
            if not _same:
                gen_cfg["electric_efficiency_half_load"] = st.number_input(
                    "Electric efficiency at 50% load (HHV)", min_value=0.01, max_value=1.0,
                    value=float(gen_cfg.get("electric_efficiency_full_load", 0.322)) * 0.9,
                    step=0.005, key="gen_half_eff")
        with h2:
            gen_cfg["min_turn_down_fraction"] = st.number_input(
                "Minimum turndown (fraction of rated capacity)",
                min_value=0.0, max_value=1.0, value=0.0, step=0.05, key="gen_turndown",
                help="generator_constraints.jl:26-36. Above zero this adds one on/off "
                     "binary per hour per unit, which makes the solve materially slower.")
        if (not _same) or gen_cfg.get("min_turn_down_fraction", 0.0) > 0:
            st.warning(
                "These two switches add 8,760 binary variables per unit and take the "
                "model beyond what the REopt web tool computes, so results are no "
                "longer directly comparable with a tool run.")

    # ---- optional fleet of several units -----------------------------------
    # REopt.jl carries CHP as an array and auto-names units (scenario.jl:490-496).
    n_gen = int(st.number_input(
        "Number of fuel-fired units", min_value=1, max_value=6, value=1, step=1,
        key="n_gen",
        help="Each unit gets its own size bounds, prices and part-load curve. "
             "Leave at 1 to match the REopt web form exactly."))
    if n_gen > 1:
        with st.expander(f"Fleet — {n_gen} units", expanded=True):
            st.caption(
                "Unit 1 uses the values above. Fixing a unit's minimum equal to its "
                "maximum pins it to a nameplate rating instead of sizing it.")
            for _g in range(1, n_gen):
                st.markdown(f"**Unit {_g + 1}**")
                q1, q2, q3, q4 = st.columns(4)
                with q1:
                    st.text_input("Name", value=f"Unit {_g + 1}", key=f"gen{_g}_name")
                    st.number_input("Installed cost ($/kW)", min_value=0.0,
                                    value=float(gen_cfg.get("installed_cost_per_kw", 800.0)),
                                    step=50.0, key=f"gen{_g}_cost")
                with q2:
                    st.number_input("Minimum capacity (kW)", min_value=0.0, value=0.0,
                                    step=10.0, key=f"gen{_g}_min")
                    st.number_input("Maximum capacity (kW)", min_value=0.0, value=1000.0,
                                    step=10.0, key=f"gen{_g}_max")
                with q3:
                    st.number_input("Electric efficiency at 100% load (HHV)",
                                    min_value=0.01, max_value=1.0,
                                    value=float(gen_cfg.get("electric_efficiency_full_load", 0.322)),
                                    step=0.005, key=f"gen{_g}_eff")
                    st.number_input("Electric efficiency at 50% load (HHV)",
                                    min_value=0.0, max_value=1.0, value=0.0, step=0.005,
                                    key=f"gen{_g}_half",
                                    help="0 means the same as full load — REopt's default.")
                with q4:
                    st.number_input("Minimum turndown (fraction)", min_value=0.0, max_value=1.0,
                                    value=0.0, step=0.05, key=f"gen{_g}_turndown")
                    st.number_input("Variable O&M ($/kWh)", min_value=0.0,
                                    value=float(gen_cfg.get("om_cost_per_kwh", 0.0)),
                                    step=0.001, format="%.3f", key=f"gen{_g}_omkwh")
else:
    n_gen = 1
""",
    "fuel part-load panel, count and fleet editor",
)

# --------------------------------------------- build the lists at run time
sub(
    """            fuel_tech=M.FuelTechInputs(enabled=(use_gen or use_chp), kind=gen_kind,
                                       label=gen_label, **gen_cfg),""",
    """            fuel_tech=_ft0,
            fuel_techs=_fleet,
            storages=_bank,""",
    "pass the fleet into the scenario",
)

sub(
    """        inp = _scenario(""",
    """        # ---- assemble the fleets. At one unit each list is None, so the
        # scenario is byte-for-byte the single-slot shape it has always been.
        _ft0 = M.FuelTechInputs(enabled=(use_gen or use_chp), kind=gen_kind,
                                label=gen_label, name=gen_label, **gen_cfg)
        _fleet = None
        if (use_gen or use_chp) and n_gen > 1:
            _fleet = [_ft0]
            for _g in range(1, n_gen):
                _cfg = dict(gen_cfg)
                _cfg["installed_cost_per_kw"] = float(ss.get(f"gen{_g}_cost", 800.0))
                _cfg["min_kw"] = float(ss.get(f"gen{_g}_min", 0.0))
                _cfg["max_kw"] = float(ss.get(f"gen{_g}_max", 1000.0))
                _cfg["electric_efficiency_full_load"] = float(ss.get(f"gen{_g}_eff", 0.322))
                _half = float(ss.get(f"gen{_g}_half", 0.0))
                _cfg["electric_efficiency_half_load"] = _half if _half > 0 else None
                _cfg["min_turn_down_fraction"] = float(ss.get(f"gen{_g}_turndown", 0.0))
                _cfg["om_cost_per_kwh"] = float(ss.get(f"gen{_g}_omkwh", 0.0))
                _fleet.append(M.FuelTechInputs(
                    enabled=True, kind=gen_kind, label=gen_label,
                    name=str(ss.get(f"gen{_g}_name") or f"Unit {_g + 1}"), **_cfg))

        _st0 = M.StorageInputs(enabled=use_bat, name="Battery 1", **bat_cfg)
        _bank = None
        if use_bat and n_bat > 1:
            _bank = [_st0]
            for _b in range(1, n_bat):
                _bank.append(M.StorageInputs(
                    enabled=True,
                    name=str(ss.get(f"bat{_b}_name") or f"Battery {_b + 1}"),
                    installed_cost_per_kwh=float(ss.get(f"bat{_b}_kwh_cost", 253.0)),
                    installed_cost_per_kw=float(ss.get(f"bat{_b}_kw_cost", 968.0)),
                    installed_cost_constant=float(ss.get(f"bat{_b}_const", 0.0)),
                    min_kwh=float(ss.get(f"bat{_b}_min_kwh", 0.0)),
                    max_kwh=float(ss.get(f"bat{_b}_max_kwh", 1_000_000.0)),
                    min_duration_hours=float(ss.get(f"bat{_b}_min_dur", 0.0)),
                    max_duration_hours=float(ss.get(f"bat{_b}_max_dur", 100000.0)),
                    can_grid_charge=bool(bat_cfg.get("can_grid_charge", True)),
                ))

        inp = _scenario(""",
    "assemble fleet lists before the scenario",
)

sub(
    """            storage=M.StorageInputs(enabled=use_bat, **bat_cfg),""",
    """            storage=_st0,""",
    "storage slot uses the assembled unit 1",
)

io.open(P, "w", encoding="utf-8").write(s)
print("fleet UI wired")
