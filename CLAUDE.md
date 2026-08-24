# GreenHouseV2

## Browser automation

Playwright MCP is configured project-scoped in `.mcp.json` (`@playwright/mcp` 0.0.79 /
Playwright 1.63.0-alpha). Verified working.

- Uses the **installed Chrome** channel (`--browser chrome`) — no Chromium download.
- Persistent profile at `.playwright/profile/` — log in once, session survives restarts.
- Relative paths in Playwright MCP tool args resolve against the **project root**.
- `browser_run_code_unsafe` runs in a VM sandbox: **no `require`, no `import`, no fs**.
  `page.screenshot({path})` still writes files. A script loaded via `filename` must
  live inside the project root.

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
