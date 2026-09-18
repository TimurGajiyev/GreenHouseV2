# GreenHouse

The project is named **GreenHouse** (the folder is still `D:\GreenHouseV2`; `D:\Greenhouse`
is a separate, older folder, so the directory was not renamed).

## Browser automation

Playwright MCP is configured project-scoped in `.mcp.json` (`@playwright/mcp` 0.0.79 /
Playwright 1.63.0-alpha). Verified working.

- Uses the **installed Chrome** channel (`--browser chrome`) — no Chromium download.
- Persistent profile at `.playwright/profile/` — log in once, session survives restarts.
- Relative paths in Playwright MCP tool args resolve against the **project root**.
- `browser_run_code_unsafe` runs in a VM sandbox: **no `require`, no `import`, no fs**.
  `page.screenshot({path})` still writes files. A script loaded via `filename` must
  live inside the project root.

## Local REopt.jl (reference engine)

Julia 1.10 LTS via juliaup (`winget install --id 9NJNWW8PVKMN -e`); environment in
`reopt_jl/`, which `develop`s the repo's own `REopt/` source (v0.61.1) + HiGHS.
Package depot is **`D:\JuliaDepot`** (C: is short on space) — always set
`JULIA_DEPOT_PATH=D:\JuliaDepot`; the Python wrapper does it for you.

- Setup once: `julia --project=reopt_jl reopt_jl/setup.jl`
- From Python: `from tools.reopt_jl import run_reopt_jl; run_reopt_jl(scenario_dict)` —
  REopt API-style JSON in, REopt's results dict out; web-tool defaults (1% gap, 600 s,
  BAU solved alongside). Cached in `reopt_test_data/reopt_jl/<sha>.json`.
- CLI: `python calculator/tools/reopt_jl.py <scenario.json> [--no-bau] [--gap=] [--time=] [--fresh]`
- Install check: `python calculator/tools/check_reopt_jl.py` (REopt's own runtests values,
  then side by side with this calculator).
- API key: read from `NLR_DEVELOPER_API_KEY` or the `.nrel_api_key` files, like the calculator.
- Gotcha: the resolver picks ArchGDAL 0.9.3, which fails to precompile on 1.10
  ("Method overwriting is not permitted"); it is pinned to 0.9.4 (REopt's own Manifest).
- First call in a fresh process spends ~1–2 min loading/compiling before solving.

## Offline docs

- `docs/reopt-jl/` — full text capture of the REopt.jl docs (14 pages, 197 KB),
  `INDEX.md` is the map.
- `screenshots/docs/` — one viewport PNG per page.
- Regenerate text: `node .playwright/scripts/extract.mjs`
- Re-shoot pages:  run `.playwright/scripts/crawl.js` via `browser_run_code_unsafe`
- Verify fidelity: `node .playwright/scripts/nestverify.mjs` compares the HTML list-depth
  profile of every page against the markdown indent profile. All 14 must read OK.

### Extraction gotchas (hard-won)

1. **Documenter destroys underscores in prose.** `a_b ... c_d` renders as
   `a<em>b ... c</em>d`, so `soc_min_fraction` becomes `socminfraction`. The extractor
   maps `<em>` back to `_`, which restores the identifier and is valid markdown for
   genuine emphasis too. There are 91 `<em>` on the Inputs page alone.
2. **One upstream docstring has a malformed code fence.** `ElectricStorage` in
   `reopt/inputs/` has an unterminated ```` ```julia ```` block, so Documenter emits it as a
   `<p>` of prose. Left alone it injects a stray fence that swallows ~34 list items into
   a phantom code block. The extractor detects a `<p>` starting with a fence and rebuilds
   it as a real code block (newlines recovered from runs of 2+ spaces).
3. All 79 docstring `<details>` render **open** by default — nothing is hidden behind
   the disclosure arrows, and the raw HTML contains their content regardless.
4. Always check code-fence parity; an odd count means a stray fence is eating content.

## Project report

`REPORT.md` at the repo root is the single consolidated document: what the calculator is,
the validation scoreboard against the live tool, findings about the REopt web tool,
the Sana'a vendor analysis, bugs fixed and known gaps. Update it rather than adding new
top-level report files.

## Context

Work relates to the REopt web tool and REopt.jl. The docs source is
`natlabrockies.github.io/REopt.jl` — branded **National Laboratory of the Rockies (NLR)**,
API keys from `developer.nlr.gov`, not NREL. Separate older folder at `D:\Greenhouse`.
