"""Shared by every step: the per-vehicle config, material type names and
the pipeline-version guard.
"""
import json
import os
import sys

from .paths import EXAMPLES, STAGING, VEHICLES, WORKSHOP, WORKSPACE


SOLID = "PHYSICAL_NRML_MAP"

TRANSPARENT = "PHYS_TRANSPARENT_NRML_MAP"

RETYPEABLE = ("PHYS_TRANSPARENT", SOLID, TRANSPARENT)

# Bump whenever `build` changes where it puts things or how the .mdl/.mtl
# reference them. The later steps rewrite a staging mod in place and assume
# build's conventions; running them against a mod built by an older pipeline
# fails silently - materials lose their transparency, textures land beside the
# paths the materials point at. The stamp below turns that into a refusal.
PIPELINE_VERSION = 2

STAMP = "port.json"

FLAT_NORMAL = "flat_normal.dds"

ICON_SUFFIXES = ("_icon20@2x.tga", "_icon20_cblend@2x.tga",
                 "_icon_small@2x.tga", "_icon_small_cblend@2x.tga",
                 "_store.tga")


def vehicle_path(name):
    """vehicles/<name>.json (your own, untracked), else examples/vehicles/."""
    for d in (VEHICLES, EXAMPLES):
        p = os.path.join(d, name + ".json")
        if os.path.exists(p):
            return p
    sys.exit("no config %s.json in %s or %s" % (name, VEHICLES, EXAMPLES))


def vehicle_names():
    """Every config in vehicles/ - what `--all` means."""
    if not os.path.isdir(VEHICLES):
        return []
    return sorted(os.path.splitext(f)[0] for f in os.listdir(VEHICLES)
                  if f.endswith(".json") and "atest" not in f
                  and not f.endswith("_golden.json"))


class Vehicle(object):
    def __init__(self, name):
        path = vehicle_path(name)
        cfg = json.load(open(path, encoding="utf-8"))
        self.name = name
        self.cfg = cfg
        self.mod_id = cfg["modId"]
        self.content_dir = cfg["contentDir"]
        self.lights = cfg.get("lights", {})
        # no "source": the Steam Workshop download of workshopId
        src = cfg.get("source") or os.path.join(WORKSHOP, str(cfg["workshopId"]))
        self.src = src if os.path.isabs(src) else os.path.join(WORKSPACE, src)
        self.dst = os.path.join(STAGING, self.mod_id)
        self.veh = os.path.join(self.dst, "content", self.content_dir)

    @property
    def res(self):
        return os.path.join(self.src, "res")

    def models(self):
        """The .mdl basenames as they end up in the staging mod."""
        return sorted(os.path.splitext(f)[0]
                      for f in os.listdir(self.veh) if f.endswith(".mdl"))


def stamp_path(v):
    return os.path.join(v.dst, "_metadata", STAMP)


def write_stamp(v):
    write(stamp_path(v), json.dumps(
        {"pipelineVersion": PIPELINE_VERSION, "vehicle": v.name}, indent=4) + "\n")


def require_fresh_build(v, step):
    """Refuse to rewrite a staging mod that a different pipeline built."""
    p = stamp_path(v)
    got = None
    if os.path.exists(p):
        got = json.load(open(p, encoding="utf-8")).get("pipelineVersion")
    if got == PIPELINE_VERSION:
        return
    sys.exit(
        "%s: staging was built by pipeline %s, this is %d.\n"
        "Refusing to run '%s' against it - the layout conventions differ and\n"
        "the damage would be silent. Run:\n"
        "    python port.py %s build\n"
        "then Bulk Convert in the Model Editor, then retry."
        % (v.mod_id, got if got is not None else "an unknown version",
           PIPELINE_VERSION, step, v.name))


def read(p):
    return open(p, encoding="utf-8-sig").read()


def write(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(s)


def tf3_name(fn):
    """TF3 wants lowercase paths; TF2 mods are full of spaces and capitals."""
    return fn.lower().replace(" ", "_")
