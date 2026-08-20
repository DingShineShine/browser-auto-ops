2026-08-19: select-radio matched the parent WSP label because it also contains the words Product Report → pick the shortest matching label
2026-08-19: calendar month button text is "Jan January" / "Aug August", not a bare abbreviation → parse any token in the button text
2026-08-19: navigating before month/year can be read overshoots to a future month → refuse to click Next/Previous until header month and year are parsed
2026-08-19: React reportName ignores a plain value setter → if fill-report-name returns empty, use browser-act state + input on the Report Name field
2026-08-20: bao daemon on another data_root blocks browser open → stop the foreign process on :8765 and start daemon in this repo
2026-08-20: PowerShell splits multiline JS for `bao eval` → generate JS in Python and pass it as one subprocess argument
2026-08-20: Date Range option Custom Date Range can be occluded for bao click → use select-downshift.py via eval
2026-08-20: fill-report-name.py eval is treated as a dangerous mutation → use `bao input` on the Report Name textbox
2026-08-20: forge generate drops execute_js calendar/download steps as noise → keep those helpers in SKILL.md; do not treat auto locators as the full replay path
