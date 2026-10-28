"""Rebuilt render server — turns render jobs into photo-real images on this PC's graphics card.

Run inside Blender (the launchers do this for you):
    blender -b --factory-startup -P render_server.py -- [--watch] [--cpu]

How it works
  jobs/*.json        queue, rendered in name order. A job is {"project": "<folder in projects/>", "preset": "<file in presets/>"}
                     plus optional overrides: "samples", "only": ["shot name", ...], "scale".
  projects/<name>/   the model to render (model.glb, genome.json, site.json) — exported by Claude from the Rebuilt model.
  presets/*.json     cameras / 360° stops, resolution, samples, sun.
  outputs/<project>/<job>/   finished images (+ job.json, log.txt).
  jobs/done/, jobs/failed/   processed jobs; a failed job leaves error.txt in its output folder.
  status.json        what the server is doing right now (read by Claude to pick up results).

--watch keeps the server running and picks up new job files as they appear; without it the queue is
processed once and the server exits. --cpu forces CPU rendering.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from rebuilt.export import blender_render as BR  # noqa: E402  (needs Blender's bpy)

JOBS, DONE, FAILED, OUT = HERE / "jobs", HERE / "jobs" / "done", HERE / "jobs" / "failed", HERE / "outputs"


def now():
    return datetime.now().isoformat(timespec="seconds")


def status(**kw):
    s = {"updated": now(), **kw}
    (HERE / "status.json").write_text(json.dumps(s, indent=1))


def run_job(jf: Path, gpu: bool):
    job = json.loads(jf.read_text())
    proj = HERE / "projects" / job["project"]
    meta = json.loads((proj / "project.json").read_text()) if (proj / "project.json").exists() else {}
    preset = json.loads((HERE / "presets" / f"{job['preset']}.json").read_text())
    out = OUT / job["project"] / jf.stem
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(jf, out / "job.json")
    shots = [s["name"] for s in preset["shots"] if not job.get("only") or s["name"] in job["only"]]
    status(state="rendering", job=jf.name, project=job["project"], shots=shots, started=now())
    t = time.time()
    files = BR.run(proj / meta.get("model", "model.glb"), proj / meta.get("genome", "genome.json"), proj / meta.get("site", "site.json"),
                   preset, out, samples=int(job.get("samples", preset.get("samples", 128))), scale=float(job.get("scale", 1.0)),
                   only=job.get("only"), gpu=gpu)
    took = time.time() - t
    (out / "log.txt").write_text(f"{now()}  {jf.name}: {len(files)} image(s) in {took:.0f}s\n" + "\n".join(files) + "\n")
    print(f"done {jf.name}: {len(files)} image(s) in {took:.0f}s", flush=True)
    return files


def main(argv):
    watch, gpu = "--watch" in argv, "--cpu" not in argv
    for d in (JOBS, DONE, FAILED, OUT):
        d.mkdir(parents=True, exist_ok=True)
    print(f"Rebuilt render server — {'GPU' if gpu else 'CPU'}, {'watching' if watch else 'one pass'} — {JOBS}", flush=True)
    while True:
        queue = sorted(p for p in JOBS.glob("*.json"))
        for jf in queue:
            try:
                run_job(jf, gpu)
                shutil.move(str(jf), DONE / jf.name)
            except Exception:
                err = traceback.format_exc()
                print(f"FAILED {jf.name}\n{err}", flush=True)
                o = OUT / "_errors"; o.mkdir(parents=True, exist_ok=True)
                (o / f"{jf.stem}.txt").write_text(err)
                shutil.move(str(jf), FAILED / jf.name)
        status(state="idle", queue=0, last_pass=now())
        if not watch:
            break
        time.sleep(10)


if __name__ == "__main__":
    a = sys.argv
    main(a[a.index("--") + 1:] if "--" in a else a[1:])
