"""Data sources REopt itself uses: bundled CRB load profiles, PVWatts, URDB.

Nothing here is synthesised. Load shapes come from the REopt.jl repository's own
``data/load_profiles`` directory; PV production comes from the same PVWatts v8
endpoint REopt calls; tariffs come from URDB.
"""

from __future__ import annotations

import datetime
import io
import json
import math
import os
import urllib.parse
import urllib.request

from .defaults import CRB_CITIES

# Repo root -> REopt/ checkout that ships the data
_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
REOPT_DIR = os.path.join(PROJECT_ROOT, "REopt")
LOAD_PROFILE_DIR = os.path.join(REOPT_DIR, "data", "load_profiles")


# ------------------------------------------------------------------ helpers
_ZONE_SHAPES = None


def _load_zone_shapes():
    """Parse REopt/data/climate_cities.shp/.dbf once (15 polygons, NAD83 degrees).

    A minimal ESRI shapefile reader -- polygon type 5 only, which is all this file
    holds -- so the lookup needs no GIS package.
    """
    global _ZONE_SHAPES
    if _ZONE_SHAPES is not None:
        return _ZONE_SHAPES
    import struct
    import numpy as np
    base = os.path.join(REOPT_DIR, "data", "climate_cities")
    with open(base + ".dbf", "rb") as fh:
        dbf = fh.read()
    nrec, hlen, rlen = struct.unpack("<IHH", dbf[4:12])
    fields, off = [], 32
    while dbf[off] != 0x0D:
        fields.append((dbf[off:off + 11].split(b"\x00")[0].decode(), dbf[off + 16]))
        off += 32
    cities = []
    for r in range(nrec):
        rec = dbf[hlen + r * rlen + 1: hlen + (r + 1) * rlen]   # skip the deletion flag
        pos, row = 0, {}
        for name, flen in fields:
            row[name] = rec[pos:pos + flen].decode("latin-1").strip()
            pos += flen
        cities.append(row.get("city", ""))
    with open(base + ".shp", "rb") as fh:
        shp = fh.read()
    shapes, off = [], 100
    while off < len(shp):
        _, clen = struct.unpack(">ii", shp[off:off + 8])
        body = off + 8
        stype, = struct.unpack("<i", shp[body:body + 4])
        if stype == 5:
            xmin, ymin, xmax, ymax = struct.unpack("<4d", shp[body + 4:body + 36])
            nparts, npts = struct.unpack("<ii", shp[body + 36:body + 44])
            parts = list(struct.unpack(f"<{nparts}i", shp[body + 44:body + 44 + 4 * nparts]))
            pstart = body + 44 + 4 * nparts
            pts = np.frombuffer(shp, dtype="<f8", count=2 * npts, offset=pstart).reshape(npts, 2)
            rings = []
            for k, a in enumerate(parts):
                b = parts[k + 1] if k + 1 < nparts else npts
                ring = pts[a:b]
                rings.append((ring[:, 0].copy(), ring[:, 1].copy(),
                              ring[:, 0].min(), ring[:, 0].max(), ring[:, 1].min(), ring[:, 1].max()))
            shapes.append(((xmin, ymin, xmax, ymax), rings))
        else:
            shapes.append(None)
        off = body + clen * 2
    _ZONE_SHAPES = list(zip(cities, shapes))
    return _ZONE_SHAPES


def _shapefile_city(lat: float, lon: float) -> str | None:
    """ArchGDAL.contains(polygon, POINT(lon lat)) -- even-odd rule over all rings."""
    import numpy as np
    for city, shape in _load_zone_shapes():
        if shape is None:
            continue
        (xmin, ymin, xmax, ymax), rings = shape
        if not (xmin <= lon <= xmax and ymin <= lat <= ymax):
            continue
        inside = False
        for xs, ys, rx0, rx1, ry0, ry1 in rings:
            if not (rx0 <= lon <= rx1 and ry0 <= lat <= ry1):
                continue
            x1, y1 = xs[:-1], ys[:-1]
            x2, y2 = xs[1:], ys[1:]
            cross = (y1 > lat) != (y2 > lat)
            with np.errstate(divide="ignore", invalid="ignore"):
                xint = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if int(np.count_nonzero(cross & (lon < xint))) % 2 == 1:
                inside = not inside
        if inside:
            return city
    return None


def find_ashrae_zone_city(lat: float, lon: float) -> tuple[str, str]:
    """REopt/src/core/doe_commercial_reference_building_loads.jl:79-121

    REopt looks the point up in REopt/data/climate_cities.shp first and returns
    that zone's city -- except LosAngeles, which (like a point outside the US)
    falls through to the nearest city by Euclidean distance in degrees. Both
    steps are reproduced here.
    """
    zones = {c: z for c, _, _, z in CRB_CITIES}
    try:
        sc = _shapefile_city(float(lat), float(lon))
    except Exception:          # a damaged or missing shapefile: REopt would error; fall back
        sc = None
    if sc is not None and sc != "LosAngeles" and sc in zones:
        return sc, zones[sc]
    best_city, best_zone, best_d = "", "", None
    for city, clat, clon, zone in CRB_CITIES:
        d = math.sqrt((lat - clat) ** 2 + (lon - clon) ** 2)
        if best_d is None or d < best_d:
            best_d, best_city, best_zone = d, city, zone
    return best_city, best_zone


def load_crb_profile(building_type: str, city: str, kind: str = "electric") -> list[float]:
    """Read one normalised 8760 CRB profile shipped with REopt.jl.

    File convention: ``data/load_profiles/<kind>/crb8760_norm_<City>_<Type>.dat``
    Each file sums to 1.0 over the year.
    """
    fname = f"crb8760_norm_{city}_{building_type}.dat"
    path = os.path.join(LOAD_PROFILE_DIR, kind, fname)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No bundled CRB profile at {path}. "
            f"Available cities: {sorted({c[0] for c in CRB_CITIES})}"
        )
    with io.open(path, encoding="utf-8") as fh:
        vals = [float(line) for line in fh if line.strip()]
    if len(vals) != 8760:
        raise ValueError(f"{fname} has {len(vals)} rows, expected 8760")
    return vals


def available_building_types(city: str, kind: str = "electric") -> list[str]:
    d = os.path.join(LOAD_PROFILE_DIR, kind)
    if not os.path.isdir(d):
        return []
    pre = f"crb8760_norm_{city}_"
    return sorted(
        f[len(pre):-4] for f in os.listdir(d) if f.startswith(pre) and f.endswith(".dat")
    )


FLAT_LOAD_TYPES = ("FlatLoad", "FlatLoad_24_5", "FlatLoad_16_7",
                   "FlatLoad_16_5", "FlatLoad_8_7", "FlatLoad_8_5")


def custom_normalized_flatload(doe_reference_name: str, year: int = 2017) -> list[float]:
    """REopt/src/core/doe_commercial_reference_building_loads.jl:278

    Verbatim port. Julia's dayofweek is Mon=1..Sun=7 and weekends = [6,7];
    Python's weekday() is Mon=0..Sun=6, so weekends are (5, 6).
    hour_range_16 = 6:21 (6am through the end of the 21st hour, i.e. 10pm)
    hour_range_8  = 9:16 (9am through the end of the 16th hour, i.e. 5pm)
    """
    periods = 8760
    start = datetime.datetime(year, 1, 1, 0, 0)
    dt_hourly = [start + datetime.timedelta(hours=i) for i in range(periods)]

    weekday_mask = [1] * periods
    hour_mask = [1] * periods
    weekends = (5, 6)
    hour_range_16 = range(6, 22)
    hour_range_8 = range(9, 17)
    if doe_reference_name != "FlatLoad":
        for i, dt in enumerate(dt_hourly):
            if doe_reference_name in ("FlatLoad_24_5", "FlatLoad_16_5", "FlatLoad_8_5"):
                if dt.weekday() in weekends:
                    weekday_mask[i] = 0
            if doe_reference_name in ("FlatLoad_16_5", "FlatLoad_16_7"):
                if dt.hour not in hour_range_16:
                    hour_mask[i] = 0
            elif doe_reference_name in ("FlatLoad_8_5", "FlatLoad_8_7"):
                if dt.hour not in hour_range_8:
                    hour_mask[i] = 0

    binary = [w * h for w, h in zip(weekday_mask, hour_mask)]
    total = sum(binary)
    return [i / total for i in binary]


def build_electric_load(building_type: str, annual_kwh: float, lat: float, lon: float) -> dict:
    """Scale the normalised CRB shape to the user's annual kWh.

    REopt/src/core/electric_load.jl -- ``BuiltInElectricLoad`` scales the
    normalised profile by ``annual_kwh``.
    """
    city, zone = find_ashrae_zone_city(lat, lon)
    if building_type in FLAT_LOAD_TYPES and building_type != "FlatLoad":
        # Shift-based flat loads are procedural and city-independent, so they carry
        # no ASHRAE-zone assumption -- the only load shapes valid outside the US.
        norm = custom_normalized_flatload(building_type)
        city, zone = building_type, "n/a"
    else:
        norm = load_crb_profile(building_type, city)
    loads_kw = [v * annual_kwh for v in norm]  # 1 h steps => kWh == kW
    return {
        "city": city,
        "ashrae_zone": zone,
        "loads_kw": loads_kw,
        "annual_kwh": sum(loads_kw),
        "peak_kw": max(loads_kw),
    }


def heating_load_mmbtu(building_type: str, city: str) -> dict:
    """Annual boiler FUEL in MMBtu, from the tables REopt ships.

    REopt's existing-boiler load is space heating + domestic hot water, taken
    from data/load_profiles/*_annual_mmbtu.json for the CRB city and building.
    """
    out = {}
    for key, fname in (("space_heating", "space_heating_annual_mmbtu.json"),
                       ("domestic_hot_water", "domestic_hot_water_annual_mmbtu.json")):
        path = os.path.join(LOAD_PROFILE_DIR, fname)
        with io.open(path, encoding="utf-8") as fh:
            table = json.load(fh)
        out[key] = float((table.get(city) or {}).get(building_type) or 0.0)
    out["fuel_mmbtu"] = out["space_heating"] + out["domestic_hot_water"]
    return out


def default_annual_kwh(building_type: str, lat: float, lon: float) -> float | None:
    """REopt/src/core/electric_load.jl:250-267 -- what a blank annual kWh means.

    The CRB table value for the building in the site's ASHRAE zone city; every
    FlatLoad variant uses the FlatLoad row.
    """
    if not building_type:
        return None
    city, _ = find_ashrae_zone_city(lat, lon)
    with io.open(os.path.join(LOAD_PROFILE_DIR, "total_electric_annual_kwh.json"), encoding="utf-8") as fh:
        table = json.load(fh)
    key = "flatload" if "FlatLoad" in building_type else building_type.lower()
    val = (table.get(city) or {}).get(key)
    return float(val) if val is not None else None


def _month_hours_2017() -> list[range]:
    """Hour ranges of each calendar month in the 8,760-hour CRB year (2017)."""
    out, h = [], 0
    for mo in range(1, 13):
        n = (datetime.date(2017 + (mo == 12), mo % 12 + 1, 1) - datetime.date(2017, mo, 1)).days * 24
        out.append(range(h, h + n))
        h += n
    return out


def build_heating_load(building_type: str, lat: float, lon: float, *,
                       annual_mmbtu: float | None = None,
                       monthly_mmbtu: list[float] | None = None,
                       addressable_load_fraction: float = 1.0,
                       boiler_efficiency: float = 0.8) -> dict:
    """Hourly heating THERMAL load, space heating + domestic hot water.

    REopt/src/core/heating_cooling_loads.jl:142 BuiltInHeatingLoad and
    doe_commercial_reference_building_loads.jl:121 built_in_load, for the two
    CRB heating loads REopt builds for an existing boiler:

      * the CRB profiles are boiler FUEL, so thermal kW =
        normalised profile x annual fuel MMBtu x boiler efficiency x 293.07107
      * with no annual input the CRB default MMBtu is used as is --
        ``addressable_load_fraction`` is only applied to a user-supplied total
        ("cannot use addressable_load_fraction with default CRB loads", :240)
      * a monthly input rescales each month of the normalised shape

    The web form takes ONE total for both loads. REopt.jl needs one per load,
    so the total is split by the CRB default space-heating / hot-water ratio for
    this building and climate zone -- the split the CRB data itself carries.
    """
    city, zone = find_ashrae_zone_city(lat, lon)
    defaults = heating_load_mmbtu(building_type, city)
    kinds = (("space_heating", defaults["space_heating"]),
             ("domestic_hot_water", defaults["domestic_hot_water"]))
    total_default = defaults["fuel_mmbtu"] or 1.0
    months = _month_hours_2017()
    per_kind = {}
    for kind, default_mmbtu in kinds:
        norm = load_crb_profile(building_type, city, kind=kind)
        share = default_mmbtu / total_default
        scale = [1.0] * 12
        if monthly_mmbtu and len(monthly_mmbtu) == 12:
            energy = 1.0
            for mo, hrs in enumerate(months):
                tot = sum(norm[h] for h in hrs)
                scale[mo] = 0.0 if tot == 0 else (monthly_mmbtu[mo] * share * addressable_load_fraction) / tot
        elif annual_mmbtu is not None:
            energy = annual_mmbtu * share * addressable_load_fraction
        else:
            energy = default_mmbtu
        kw = []
        for mo, hrs in enumerate(months):
            for h in hrs:
                kw.append(norm[h] * energy * scale[mo] * boiler_efficiency * 293.07107)
        per_kind[kind] = kw
    loads_kw = [a + b for a, b in zip(per_kind["space_heating"], per_kind["domestic_hot_water"])]
    fuel = sum(loads_kw) / (boiler_efficiency * 293.07107)
    if monthly_mmbtu and len(monthly_mmbtu) == 12:
        unaddressable = sum(monthly_mmbtu) * (1 - addressable_load_fraction)
    elif annual_mmbtu is not None:
        unaddressable = annual_mmbtu * (1 - addressable_load_fraction)
    else:
        unaddressable = 0.0
    return {
        "city": city, "ashrae_zone": zone,
        "loads_kw": loads_kw,                                   # thermal kW, 8,760
        "space_heating_kw": per_kind["space_heating"],
        "dhw_kw": per_kind["domestic_hot_water"],
        "annual_fuel_mmbtu": fuel,                              # addressable boiler fuel
        "unaddressable_fuel_mmbtu": unaddressable,
        "peak_kw": max(loads_kw) if loads_kw else 0.0,
        "avg_fuel_mmbtu_per_hour": fuel / 8760.0,
    }


# ----------------------------------------------------------------- PVWatts
def _api_key() -> str:
    key = os.environ.get("NLR_DEVELOPER_API_KEY", "").strip()
    if key:
        return key
    # fall back to the key file the user already has on disk
    for cand in (
        os.path.join(PROJECT_ROOT, ".nrel_api_key"),
        r"D:\Greenhouse\.nrel_api_key",
    ):
        if os.path.exists(cand):
            with io.open(cand, encoding="utf-8") as fh:
                k = fh.read().strip()
            if k:
                return k
    raise RuntimeError(
        "No API key. Set NLR_DEVELOPER_API_KEY (free from https://developer.nlr.gov)."
    )


def call_pvwatts_api(
    latitude: float,
    longitude: float,
    *,
    tilt: float | None = None,
    azimuth: float = 180,
    module_type: int = 0,
    array_type: int = 1,
    losses: float = 14,
    dc_ac_ratio: float = 1.2,
    gcr: float = 0.4,
    inv_eff: float = 96,
    timeframe: str = "hourly",
    radius: int = 0,
    timeout: int = 60,
) -> tuple[list[float], list[float]]:
    """REopt/src/core/utils.jl:475-513

    Returns (production factor for a 1 kW system, ambient temp degC), 8760 each.
    REopt scales the PVWatts ``ac`` output (W) by 1/1000 for a 1 kW system.
    """
    if tilt is None:
        tilt = latitude
    params = {
        "api_key": _api_key(),
        "lat": latitude,
        "lon": longitude,
        "tilt": tilt,
        "system_capacity": 1,
        "azimuth": azimuth,
        "module_type": module_type,
        "array_type": array_type,
        "losses": losses,
        "dc_ac_ratio": dc_ac_ratio,
        "gcr": gcr,
        "inv_eff": inv_eff,
        "timeframe": timeframe,
        "radius": radius,
    }
    url = "https://developer.nlr.gov/api/pvwatts/v8.json?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "REopt.jl"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode("utf-8"))
    if resp.get("errors"):
        raise RuntimeError(f"Bad response from PVWatts: {resp['errors']}")
    watts = [w / 1000.0 for w in resp["outputs"].get("ac", [])]
    tamb = list(resp["outputs"].get("tamb", []))
    if len(watts) != 8760:
        raise RuntimeError(f"PVWatts did not return a valid prodfactor (got {len(watts)})")
    return watts, tamb


# -------------------------------------------------------------------- URDB
def fetch_urdb_rate(urdb_label: str, timeout: int = 60) -> dict:
    """Fetch one URDB rate document by label (the id the web tool submits)."""
    params = {
        "version": 8,
        "format": "json",
        "detail": "full",
        "getpage": urdb_label,
        "api_key": _api_key(),
    }
    url = "https://api.openei.org/utility_rates?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "REopt-calculator"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        doc = json.loads(r.read().decode("utf-8"))
    items = doc.get("items") or []
    if not items:
        raise RuntimeError(f"URDB returned no rate for label {urdb_label}")
    return items[0]


def urdb_rates_by_location(lat: float, lon: float, timeout: int = 60) -> list[dict]:
    """List rates available at a location, as the tool's rate dropdown does."""
    params = {
        "version": 8,
        "format": "json",
        "detail": "minimal",
        "lat": lat,
        "lon": lon,
        "radius": 20,
        "approved": "true",
        "limit": 250,
        "api_key": _api_key(),
    }
    url = "https://api.openei.org/utility_rates?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "REopt-calculator"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        doc = json.loads(r.read().decode("utf-8"))
    return doc.get("items") or []
