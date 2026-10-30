# Notes for Claude working in this repo

- This is the Rebuilt toolkit (code only). House data lives in the sibling repo `carter671/rebuilt-properties`; clone it next to this one when a task needs a house.
- The process is in `docs/WORKFLOW.md`; the `rebuilt-house-workflow` skill (if loaded) follows the same steps.
- Before changing code: `pip install -e . && pytest -q`. After: tests green, then commit on a branch and open a PR (never push to `main` directly unless the user says so).
- The people using this are not construction people: keep replies short and plain, show pictures, label first-pass engineering as needing an engineer's sign-off, and never invent property facts.
- Prices in `src/rebuilt/takeoff/pricebook.py` are placeholders until real job costs are imported; say so on every budget.

## Two people work on this (Carter and Kevin)
- Start every session with `git fetch origin` in both repos and say in one line what the other person changed since (new branches, merged PRs, new houses). Build on `main`; if an unmerged branch already has what you need, say so instead of redoing it.
- Merge finished work to `main` the same day (after tests pass and the user says so), so the other person's Claude starts from it. Keep branches small and short-lived.
- Republish an editor only from code that is on `main` (or the branch the user names), and never over a page you don't have edit access to.
- Every new page (editor, model, walk sheet, scope): add it to `rebuilt-properties/PAGES.md` (house, page, link, owner) and commit to main, then tell the user to open it → Share → add the other person with edit. Claude cannot change sharing.
- Before working on a house's editor, pull its designs from the page database; the other person may have edited since.
