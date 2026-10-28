"""rebuilt — command-line interface.

  rebuilt schema [OUT]                         write the Genome JSON Schema
  rebuilt validate GENOME [--profile P]        layered validation report
  rebuilt build GENOME OUT_DIR [--profile P]   compile + IFC + GLB + PDF + viewer + reports
  rebuilt init PROJECT GENOME                  start a project directory
  rebuilt capture PROJECT FILE[:by] ...        ingest evidence, register observations, create proposals
  rebuilt proposals PROJECT [--all]            list proposals with evidence
  rebuilt decide PROJECT PID accept|reject|dispute --by NAME [--reason R] [--value V] [--candidate N] [--subjects A,B]
  rebuilt edit PROJECT ELEMENT PARAM VALUE --by NAME --reason R [--basis B] [--unc U] [--verify]
  rebuilt verify PROJECT ELEMENT PARAM --by NAME --reason R
  rebuilt apply PROJECT CORRECTION.json         apply a correction downloaded from the viewer
  rebuilt close-capture PROJECT --by NAME --reason R   accept all gathered evidence as verified (one changeset)
  rebuilt next PROJECT                         next-best measurements
  rebuilt status PROJECT                       revision, replay check, open proposals, profile readiness
  rebuilt render PROJECT                       build PROJECT/out from the current genome
  rebuilt scope GENOME OUT.json [--design D] [--prices P] [--contingency 0.10]
                                               design + takeoff + priced rehab scope
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .genome.io import load
from .genome.schema import json_schema
from .genome.validate import validate
from .units import UnitError, parse_length, parse_pitch


def _load(path):
    g, issues = load(path)
    for i in issues.items:
        if i.severity != "info":
            print(f"  [{i.severity}] {i.code}: {i.message}", file=sys.stderr)
    if g is None:
        sys.exit(2)
    return g


def build(g, out_dir, profile="review", name="model"):
    from .export.report import export_all
    from .export.viewer import write_viewer
    from .model.compile import CompileError, compile_genome

    try:
        model = compile_genome(g, profile)
    except CompileError as e:
        for i in e.issues.sorted():
            print(f"  [{i.severity}] {i.code}: {i.message}")
        sys.exit(3)
    rep = export_all(model, g, out_dir, name)
    write_viewer(Path(out_dir) / f"{name}.glb", Path(out_dir) / f"{name}.meta.json", Path(out_dir) / "viewer.html")
    return model, rep


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rebuilt")
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("schema"); a.add_argument("out", nargs="?")
    a = sp.add_parser("validate"); a.add_argument("genome"); a.add_argument("--profile", default="review")
    a = sp.add_parser("build"); a.add_argument("genome"); a.add_argument("out"); a.add_argument("--profile", default="review")
    a = sp.add_parser("init"); a.add_argument("project"); a.add_argument("genome")
    a = sp.add_parser("capture"); a.add_argument("project"); a.add_argument("files", nargs="+"); a.add_argument("--by", default="capture")
    a = sp.add_parser("proposals"); a.add_argument("project"); a.add_argument("--all", action="store_true")
    a = sp.add_parser("decide"); a.add_argument("project"); a.add_argument("pid"); a.add_argument("decision", choices=["accept", "reject", "dispute"])
    a.add_argument("--by", required=True); a.add_argument("--reason", default=""); a.add_argument("--value")
    a.add_argument("--candidate", type=int); a.add_argument("--subjects")
    a = sp.add_parser("edit"); a.add_argument("project"); a.add_argument("element"); a.add_argument("param"); a.add_argument("value")
    a.add_argument("--by", required=True); a.add_argument("--reason", required=True); a.add_argument("--basis", default="measured")
    a.add_argument("--unc"); a.add_argument("--verify", action="store_true")
    a = sp.add_parser("verify"); a.add_argument("project"); a.add_argument("element"); a.add_argument("param")
    a.add_argument("--by", required=True); a.add_argument("--reason", required=True)
    a = sp.add_parser("apply"); a.add_argument("project"); a.add_argument("correction_json")
    a = sp.add_parser("close-capture"); a.add_argument("project"); a.add_argument("--by", required=True); a.add_argument("--reason", required=True)
    a = sp.add_parser("scope"); a.add_argument("genome"); a.add_argument("out")
    a.add_argument("--design"); a.add_argument("--prices"); a.add_argument("--contingency", type=float, default=0.10); a.add_argument("--page"); a.add_argument("--title", default="Rehab Scope")
    for c in ("next", "status", "render"):
        a = sp.add_parser(c); a.add_argument("project")
    args = ap.parse_args(argv)

    if args.cmd == "scope":
        from .takeoff.run import run_scope
        res = run_scope(args.genome, args.design, args.prices, args.contingency)
        Path(args.out).write_text(json.dumps(res, indent=1, default=float))
        if args.page:
            from .takeoff.page import build_page
            build_page(res, args.page, args.title)
        p = res["priced"]
        for t, v in p["by_trade"].items():
            print(f"  {t:12} ${v:>12,.0f}")
        print(f"  {'subtotal':12} ${p['subtotal']:>12,.0f}\n  {'contingency':12} ${p['contingency']:>12,.0f}\n  {'TOTAL':12} ${p['total']:>12,.0f}")
        return
    if args.cmd == "schema":
        s = json.dumps(json_schema(), indent=1)
        Path(args.out).write_text(s) if args.out else print(s)
    elif args.cmd == "validate":
        g = _load(args.genome)
        issues = validate(g, args.profile)
        for i in issues.sorted():
            print(f"[{i.severity}] {i.layer}/{i.code}: {i.message}")
        print(f"{len(issues.errors)} errors, {len(issues.warnings)} warnings (profile {args.profile})")
        sys.exit(1 if issues.errors else 0)
    elif args.cmd == "build":
        g = _load(args.genome)
        model, rep = build(g, args.out, args.profile)
        v = rep["targets"]["ifc"]["validation"]
        print(f"model {model.model_hash[:12]}  elements {len(model.elements)}  issues {len(model.issues.items)}  "
              f"IFC validation {'PASS' if v['ok'] else 'FAIL'}  → {args.out}")
    elif args.cmd == "init":
        from .review.project import Project
        Project.init(args.project, args.genome)
        print(f"initialised {args.project}")
    elif args.cmd == "capture":
        from .capture.pipeline import run_capture
        from .review.project import Project
        p = Project(args.project)
        files = [(f.split(":")[0], f.split(":")[1] if ":" in f else args.by) for f in args.files]
        g, cs, props, unproc = run_capture(p.genome(), p.evidence, files, args.by)
        if cs:
            p.record_applied(g, cs)
        p.add_proposals(props)
        print(f"registered {sum(1 for o in (cs or {'ops': []})['ops'] if '/observations/' in o['path'])} observations; "
              f"{len(props)} proposals; {len(unproc)} files awaiting extractors")
        for u in unproc:
            print(f"  - {u['filename']}: {u['reason']}")
    elif args.cmd == "proposals":
        from .review.project import Project
        for pr in Project(args.project).proposals():
            if pr["status"] != "pending" and not args.all:
                continue
            tgt = pr.get("subject") or ",".join(c["element"] for c in pr.get("candidates", []) if "element" in c) or "?"
            print(f"{pr['id']} [{pr['status']}] {pr['kind']:<18} {tgt}.{pr.get('property')}  — {pr['rationale']}")
            if pr.get("proposed"):
                print(f"      proposed {pr['proposed']['value']:.4f} ({pr['proposed']['basis']} ±{pr['proposed']['uncertainty']:.4f}); current {pr.get('current')}")
            for c in pr.get("candidates", []):
                print(f"      candidate {c}")
            for e in pr.get("evidence", []):
                print(f"      evidence {e['source']} {e['locator']}: \"{e['excerpt']}\"")
    elif args.cmd == "decide":
        from .review.project import Project
        p = Project(args.project)
        val = None
        if args.value:
            prop = next(x for x in p.proposals() if x["id"] == args.pid).get("property")
            val = parse_pitch(args.value) if prop == "pitch" else parse_length(args.value, default_unit="m")
        p.decide(args.pid, args.decision, args.by, args.reason, val, args.candidate,
                 args.subjects.split(",") if args.subjects else None)
        print("ok")
    elif args.cmd == "edit":
        from .review.project import Project
        try:
            g = Project(args.project).edit(args.element, args.param, args.value, args.by, args.reason, args.basis, args.unc, args.verify)
        except UnitError as e:
            print(e); sys.exit(2)
        print(f"genome revision {g.revision.number}")
    elif args.cmd == "apply":
        from .review.project import Project
        c = json.loads(Path(args.correction_json).read_text())
        p = Project(args.project)
        if c.get("genome_revision") is not None and c["genome_revision"] != p.genome().revision.number:
            print(f"note: correction was made against revision {c['genome_revision']}; current is {p.genome().revision.number}")
        for e in c["edits"]:
            g = p.edit(e["element"], e["param"], e["value_text"], c["author"], c["reason"], e.get("basis", "measured"))
        print(f"genome revision {g.revision.number}")
    elif args.cmd == "close-capture":
        from .review.project import Project
        g = Project(args.project).close_capture(args.by, args.reason)
        print(f"capture closed; genome revision {g.revision.number}; {g.revision.history[-1].ops} ops")
    elif args.cmd == "verify":
        from .review.project import Project
        g = Project(args.project).verify_value(args.element, args.param, args.by, args.reason)
        print(f"genome revision {g.revision.number}")
    elif args.cmd == "next":
        from .capture.pipeline import next_best
        from .model.compile import compile_genome
        from .review.project import Project
        p = Project(args.project)
        g = p.genome()
        unk = {(pr.get("subject"), pr.get("property")) for pr in p.proposals() if pr["kind"] == "note_unknown"}
        for r in next_best(g, compile_genome(g, check_overlaps=False), unk):
            print(f"{r['score']:7.2f}  {r['element']}.{r['param']:<14} {r['why']:<34} → {r['action']}")
    elif args.cmd == "status":
        from .review.project import Project
        p = Project(args.project)
        g = p.genome()
        open_ = [x for x in p.proposals() if x["status"] == "pending"]
        print(f"genome revision {g.revision.number}; changes replay to current: {p.verify_replay()}; pending proposals: {len(open_)}")
        for prof in ("sketch", "review", "ifc-exchange", "verified"):
            n = len(validate(g, prof).errors)
            print(f"  profile {prof:<13} {'READY' if n == 0 else f'{n} blocking issues'}")
    elif args.cmd == "render":
        from .review.project import Project
        p = Project(args.project)
        model, rep = build(p.genome(), p.out)
        print(f"rendered rev {model.genome_revision} → {p.out}")


if __name__ == "__main__":
    main()
