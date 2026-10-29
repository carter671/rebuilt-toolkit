"""Build the click-and-drag design editor page for one property.

    python3 -m rebuilt.design.editor_export AS_BUILT.genome.json OUT/model.glb plan.json --name "123 Main St"
    python3 build.py plan.json "123 Main St" index.html [--base-id ID] [--site site.json] [--title "Short Name Editor"]
    (site.json from rebuilt/site/lot_import.py adds the lot lines + setbacks for the lot check)

Saved designs are tied to the page's base id. When REBUILDING an editor that already has designs, pass the live page's
base id (search its HTML for "base_id") or the old designs will not show. Winchester TEST copy: winchester-test-cfaf8b2a.

then publish index.html as an artifact with capabilities {db:{}, user:{}, sample:{}} (designs are saved in db collection "designs").
"""
import json, re, sys, hashlib
from pathlib import Path
args = [a for a in sys.argv[1:]]
base_id = site = title = None
if "--title" in args:
    i = args.index("--title"); title = args[i + 1]; del args[i:i + 2]
if "--site" in args:
    i = args.index("--site"); site = json.loads(Path(args[i + 1]).read_text()); del args[i:i + 2]
if "--base-id" in args:
    i = args.index("--base-id"); base_id = args[i + 1]; del args[i:i + 2]
src, name = args[0], args[1]
out = Path(args[2] if len(args) > 2 else Path(__file__).parent / "index.html")
plan = json.loads(Path(src).read_text())
keepcat = re.compile(r"toilet|tub|shower|vanity|sink|cabinet|range|fridge|washer|dryer|water heater|furnace|bed|sofa|table", re.I)
plan["comps"] = [c for c in plan["comps"] if keepcat.search(c["name"] + " " + c["cat"] + " " + c["kind"])]
plan["name"] = name
if site:
    plan["site"] = site
plan["base_id"] = base_id or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") + "-" + hashlib.sha1(json.dumps(plan["walls"]).encode()).hexdigest()[:8]
html = (Path(__file__).parent / "template.html").read_text().replace("__PLAN__", json.dumps(plan, separators=(",", ":")))
if title:
    html = html.replace("<title>Rebuilt Design Editor</title>", f"<title>{title}</title>", 1)
out.write_text(html)
print(len(plan["comps"]), "comps;", plan["base_id"], len(html) // 1024, "KB ->", out)
