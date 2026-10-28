# Notes for Claude working in this repo

- This is the Rebuilt toolkit (code only). House data lives in the sibling repo `carter671/rebuilt-properties`; clone it next to this one when a task needs a house.
- The process is in `docs/WORKFLOW.md`; the `rebuilt-house-workflow` skill (if loaded) follows the same steps.
- Before changing code: `pip install -e . && pytest -q`. After: tests green, then commit on a branch and open a PR (never push to `main` directly unless the user says so).
- The people using this are not construction people: keep replies short and plain, show pictures, label first-pass engineering as needing an engineer's sign-off, and never invent property facts.
- Prices in `src/rebuilt/takeoff/pricebook.py` are placeholders until real job costs are imported; say so on every budget.
