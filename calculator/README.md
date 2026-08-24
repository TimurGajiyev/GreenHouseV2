# REopt calculator

A working subset of the REopt web tool: steps 1–5, four technologies
(Prime Generator / Generator, CHP, PV, Battery).

```bash
pip install streamlit pulp highspy pandas altair
streamlit run calculator/streamlit_app.py
```

Needs a free API key from <https://developer.nlr.gov> for PVWatts and URDB:
set `NLR_DEVELOPER_API_KEY`, or put the key in `.nrel_api_key`.

Full documentation — provenance of every formula, the validation scoreboard,
findings about the REopt web tool, and known gaps — is in
[`../REPORT.md`](../REPORT.md).

`reopt_core/ui_fields.py` is **generated** from `reopt_test_data/ui-spec.json`.
Do not hand-edit it; run `python calculator/tools/gen_ui_fields.py`.
