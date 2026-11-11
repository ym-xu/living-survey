#!/usr/bin/env python3
"""Run the pipeline for every field and build the whole site.

Two layouts, chosen by what is in the repository:

  * one field  — map.toml (+ notes.toml) at the top, data in data/, the page at /.
                 This is the template: fork it, edit map.toml, done.
  * many fields — fields/<id>/map.toml (+ notes.toml), data in data/fields/<id>/,
                 each map at /fields/<id>/, a catalog of all maps at /.
                 Settings for the catalog live in fields/catalog.toml.

    python3 scripts/build.py fetch            # fetch.py for every field
    python3 scripts/build.py cards [args]     # cards.py for every field (args passed on)
    python3 scripts/build.py build --base-url https://you.github.io/repo/
    python3 scripts/build.py serve [field]    # preview: one field live, or the whole site

A field whose map.toml is broken is reported and skipped; the others still run.
Standard library only (plus the hugo binary for build/serve).
"""
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from email.utils import format_datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIELDS = os.path.join(ROOT, "fields")
CATALOG = os.path.join(FIELDS, "catalog.toml")
FEED_ITEMS = 40           # newest papers per subfield feed
RECENT_DAYS = 14          # papers per field kept in the catalog for "my feed"


def fields(root=ROOT):
    """[{id, map, notes, data, out}] — out is the path under the site root ('' = the root)."""
    fdir = os.path.join(root, "fields")
    found = sorted(d for d in os.listdir(fdir) if os.path.isfile(os.path.join(fdir, d, "map.toml"))) \
        if os.path.isdir(fdir) else []
    if not found:
        return [{"id": "", "map": os.path.join(root, "map.toml"), "notes": os.path.join(root, "notes.toml"),
                 "data": os.path.join(root, "data"), "out": "", "src": "map.toml"}]
    order = catalog_settings(root).get("order") or []
    found.sort(key=lambda f: (order.index(f) if f in order else len(order), f))
    return [{"id": f, "map": os.path.join(fdir, f, "map.toml"), "notes": os.path.join(fdir, f, "notes.toml"),
             "data": os.path.join(root, "data", "fields", f), "out": f"fields/{f}/", "src": f"fields/{f}/map.toml"}
            for f in found]


def catalog_settings(root=ROOT):
    try:
        with open(os.path.join(root, "fields", "catalog.toml"), "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def env_for(field):
    return dict(os.environ, LS_MAP=field["map"], LS_NOTES=field["notes"], LS_DATA=field["data"])


def run_scripts(script, args):
    """Run scripts/<script> once per field. Returns the ids that failed."""
    failed = []
    for f in fields():
        print(f"== {f['id'] or 'map'}: {script}", file=sys.stderr, flush=True)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", script), *args], env=env_for(f))
        if r.returncode:
            failed.append(f["id"] or "map")
            # a GitHub Actions annotation, so a broken field is visible without failing the others
            print(f"::error title={f['src']}::{script} failed for this field; its page keeps the last data", file=sys.stderr)
    return failed


# ------------------------------------------------------------------- data ----
def load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None


def load_map(path):
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return {}


def catalog_data(root=ROOT):
    """What the catalog page shows: every field with its numbers, and its recent papers
    (for the in-browser "my feed"; nothing about the viewer leaves the browser)."""
    out = []
    for f in fields(root):
        m = load_map(f["map"]).get("map", {})
        d = load_json(os.path.join(f["data"], "survey.json")) or {}
        today = d.get("today")
        cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=RECENT_DAYS)).isoformat() if today else ""
        out.append({
            "id": f["id"], "path": f["out"],
            "title": m.get("title", f["id"]), "description": m.get("description", ""),
            "updated": d.get("updated", ""), "total": d.get("total", 0), "last4w": d.get("last4w", 0),
            "subfields": [{"id": s["id"], "name": s["name"], "short": s.get("short", s["name"]), "count": s["count"],
                           "last4w": s["last4w"], "trend": s["trend"]} for s in d.get("subfields", [])],
            "recent": [{"id": p["id"], "title": p["title"], "date": p["date"], "tags": p["tags"],
                        "authors": p["authors"][:3], "venue": p.get("venue", "")}
                       for p in d.get("papers", []) if p["date"] >= cutoff and not p.get("app")],
        })
    return {"fields": out, "settings": catalog_settings(root), "recent_days": RECENT_DAYS}


def write_feeds(field, outdir, base_url):
    """feeds/<subfield>.xml: the newest papers of one subfield, for feed readers and RSS-to-email."""
    d = load_json(os.path.join(field["data"], "survey.json"))
    if not d:
        return 0
    title = load_map(field["map"]).get("map", {}).get("title", "Living Survey")
    page = base_url.rstrip("/") + "/" + field["out"]
    os.makedirs(os.path.join(outdir, "feeds"), exist_ok=True)
    now = format_datetime(dt.datetime.now(dt.timezone.utc))
    for s in d.get("subfields", []):
        rss = ET.Element("rss", version="2.0")
        ch = ET.SubElement(rss, "channel")
        ET.SubElement(ch, "title").text = f"{s['name']} — {title}"
        ET.SubElement(ch, "link").text = f"{page}#tag={s['id']}"
        ET.SubElement(ch, "description").text = s.get("desc") or s["name"]
        ET.SubElement(ch, "lastBuildDate").text = now
        n = 0
        for p in d.get("papers", []):
            if s["id"] not in p["tags"] or p.get("app"):
                continue
            it = ET.SubElement(ch, "item")
            ET.SubElement(it, "title").text = p["title"]
            ET.SubElement(it, "link").text = f"https://arxiv.org/abs/{p['id']}"
            ET.SubElement(it, "guid", isPermaLink="true").text = f"https://arxiv.org/abs/{p['id']}"
            ET.SubElement(it, "pubDate").text = format_datetime(dt.datetime.fromisoformat(p["date"]).replace(tzinfo=dt.timezone.utc))
            ET.SubElement(it, "description").text = " · ".join(x for x in (", ".join(p["authors"]), p.get("venue", "")) if x) \
                + "\n\n" + p.get("abs", "")
            n += 1
            if n == FEED_ITEMS:
                break
        ET.ElementTree(rss).write(os.path.join(outdir, "feeds", f"{s['id']}.xml"), encoding="utf-8", xml_declaration=True)
    return len(d.get("subfields", []))


# ------------------------------------------------------------------ build ----
def hugo_config(tmp, name, base_url, publish, data_dir, map_path=None, notes_path=None, params=None):
    """An extra Hugo config layered over hugo.toml: where this page's data comes from."""
    q = json.dumps
    lines = [f"baseURL = {q(base_url)}", f"publishDir = {q(publish)}"]
    lines += ["[params]"] + [f"{k} = {q(v)}" for k, v in (params or {}).items()]
    lines += ["[module]", "[[module.mounts]]", f"source = {q(data_dir)}", 'target = "data"']
    for src, tgt in ((map_path, "data/map.toml"), (notes_path, "data/notes.toml")):
        if src:
            lines += ["[[module.mounts]]", f"source = {q(src)}", f"target = {q(tgt)}"]
    path = os.path.join(tmp, f"{name}.toml")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def hugo(*args):
    r = subprocess.run(["hugo", "--minify", "--quiet", *args], cwd=ROOT)
    if r.returncode:
        sys.exit(f"hugo failed ({' '.join(args)})")


def build(base_url, public):
    base_url = base_url.rstrip("/") + "/"
    fs = fields()
    if os.path.isdir(public):
        shutil.rmtree(public)
    with tempfile.TemporaryDirectory() as tmp:
        for f in fs:
            out = os.path.join(public, f["out"])
            cfg = hugo_config(tmp, f["id"] or "map", base_url + f["out"], out, f["data"], f["map"], f["notes"],
                              params={"mapPath": os.path.relpath(f["map"], ROOT), "notesPath": os.path.relpath(f["notes"], ROOT),
                                      "catalogURL": base_url if f["id"] else ""})
            hugo("--config", f"hugo.toml,{cfg}")
            n = write_feeds(f, out, base_url)
            print(f"  built {f['out'] or '/'} ({n} subfield feeds)", file=sys.stderr)
        if fs[0]["id"]:                                  # many fields: the catalog at the root
            cdir = os.path.join(tmp, "catalog-data")
            os.makedirs(cdir)
            with open(os.path.join(cdir, "catalog.json"), "w", encoding="utf-8") as fh:
                json.dump(catalog_data(), fh, ensure_ascii=False)
            cfg = hugo_config(tmp, "catalog", base_url, public, cdir, params={"catalog": True})
            hugo("--config", f"hugo.toml,{cfg}")
            print(f"  built / (catalog of {len(fs)} fields)", file=sys.stderr)


def serve(field_id):
    fs = fields()
    if field_id:
        f = next((x for x in fs if x["id"] == field_id), None)
        if not f:
            sys.exit(f"no field {field_id!r}; fields: {', '.join(x['id'] for x in fs)}")
        with tempfile.TemporaryDirectory() as tmp:
            cfg = hugo_config(tmp, f["id"], "http://localhost:1313/", os.path.join(tmp, "out"), f["data"], f["map"], f["notes"],
                              params={"mapPath": os.path.relpath(f["map"], ROOT), "notesPath": os.path.relpath(f["notes"], ROOT)})
            subprocess.run(["hugo", "server", "--config", f"hugo.toml,{cfg}"], cwd=ROOT)
        return
    public = os.path.join(ROOT, "public")
    build("http://localhost:8000/", public)
    print("serving the whole site at http://localhost:8000/ (rebuild to see changes; "
          "`serve <field>` reloads one field live)", file=sys.stderr)
    subprocess.run([sys.executable, "-m", "http.server", "8000", "--bind", "127.0.0.1", "-d", public])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    c = sub.add_parser("cards")
    c.add_argument("rest", nargs=argparse.REMAINDER)
    b = sub.add_parser("build")
    b.add_argument("--base-url", default="http://localhost:1313/")
    b.add_argument("--out", default=os.path.join(ROOT, "public"))
    s = sub.add_parser("serve")
    s.add_argument("field", nargs="?")
    a = ap.parse_args()
    if a.cmd == "fetch":
        sys.exit(1 if run_scripts("fetch.py", []) else 0)
    if a.cmd == "cards":
        sys.exit(1 if run_scripts("cards.py", a.rest) else 0)
    if a.cmd == "build":
        build(a.base_url, os.path.abspath(a.out))
    if a.cmd == "serve":
        serve(a.field)


if __name__ == "__main__":
    main()
