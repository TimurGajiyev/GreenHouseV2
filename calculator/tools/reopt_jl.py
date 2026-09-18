"""Reference results from the local REopt.jl -- no web tool, no rate limit.

    from tools.reopt_jl import run_reopt_jl
    res = run_reopt_jl(scenario_dict)            # BAU + optimal, 1% gap, 600 s
    res["Financial"]["lcc"], res["CHP"]["size_kw"], ...

    python tools/reopt_jl.py REopt/test/scenarios/chp_payback.json [--no-bau] [--gap=0.01] [--time=600] [--fresh]

The scenario is REopt's own JSON (the same dict the API takes). Results are the
dict REopt.jl returns, cached in reopt_test_data/reopt_jl/<sha>.json by scenario
and solver options, so a case is solved once. Julia is found through juliaup;
its package depot lives on D: (D:\\JuliaDepot) to keep C: free. One-time setup:

    julia --project=reopt_jl reopt_jl/setup.jl
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_DIR = os.path.join(ROOT, "reopt_jl")
CACHE = os.path.join(ROOT, "reopt_test_data", "reopt_jl")
DEPOT = r"D:\JuliaDepot"


def julia_exe() -> str:
    exe = shutil.which("julia") or os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "julia.exe")
    if not os.path.exists(exe):
        raise RuntimeError("Julia not found -- install with: winget install --id 9NJNWW8PVKMN -e")
    return exe


def run_reopt_jl(scenario: dict, *, bau: bool = True, gap: float = 0.01, time_limit: float = 600.0,
                 fresh: bool = False, timeout: float | None = None) -> dict:
    """Solve ``scenario`` with REopt.jl; return REopt's results dict (cached)."""
    blob = json.dumps(scenario, sort_keys=True)
    key = hashlib.sha256(f"{blob}|bau={bau}|gap={gap}|t={time_limit}".encode()).hexdigest()[:16]
    os.makedirs(CACHE, exist_ok=True)
    out = os.path.join(CACHE, f"{key}.json")
    if os.path.exists(out) and not fresh:
        with io.open(out, encoding="utf-8") as fh:
            return json.load(fh)
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "scenario.json")
        with io.open(src, "w", encoding="utf-8") as fh:
            fh.write(blob)
        cmd = [julia_exe(), f"--project={ENV_DIR}", os.path.join(ENV_DIR, "run.jl"), src, out,
               f"--gap={gap}", f"--time={time_limit}"] + ([] if bau else ["--no-bau"])
        env = dict(os.environ, JULIA_DEPOT_PATH=DEPOT)
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout or (2 * time_limit + 600))
        if p.returncode != 0 or not os.path.exists(out):
            raise RuntimeError(f"REopt.jl failed (exit {p.returncode}):\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")
    with io.open(out, encoding="utf-8") as fh:
        return json.load(fh)


def _summary(r: dict) -> None:
    f = r.get("Financial", {})
    print(f"status {r.get('status')}   ({r.get('_runner', {}).get('seconds')} s)")
    for k in ("lcc", "lcc_bau", "npv", "simple_payback_years", "internal_rate_of_return",
              "initial_capital_costs", "initial_capital_costs_after_incentives"):
        if k in f:
            print(f"  Financial.{k:<40} {f[k]:>18,.4f}")
    for tech, keys in (("PV", ("size_kw",)), ("ElectricStorage", ("size_kw", "size_kwh")),
                       ("CHP", ("size_kw", "annual_electric_production_kwh", "annual_thermal_production_mmbtu")),
                       ("Generator", ("size_kw",)), ("ExistingBoiler", ("annual_fuel_consumption_mmbtu",))):
        for k in keys:
            if k in r.get(tech, {}):
                print(f"  {tech}.{k:<40} {r[tech][k]:>18,.4f}")


if __name__ == "__main__":
    args = sys.argv[1:]
    paths = [a for a in args if not a.startswith("--")]
    if len(paths) != 1:
        sys.exit(__doc__)
    opt = {a.split("=")[0][2:]: a.split("=")[1] for a in args if "=" in a}
    with io.open(paths[0], encoding="utf-8") as fh:
        scen = json.load(fh)
    res = run_reopt_jl(scen, bau="--no-bau" not in args, gap=float(opt.get("gap", 0.01)),
                       time_limit=float(opt.get("time", 600)), fresh="--fresh" in args)
    _summary(res)
