"""particles: exhaust and steam emitters."""
import collections
import os
import re

from .common import read, write


ALPHA_OVER_LIFETIME = """\t\t\t\t\t\talphaOverLifeTime = {
\t\t\t\t\t\t\tcurve = {
\t\t\t\t\t\t\t\t{
\t\t\t\t\t\t\t\t\teasing = "Linear",
\t\t\t\t\t\t\t\t\ttime = 0,
\t\t\t\t\t\t\t\t\tvalue = %s,
\t\t\t\t\t\t\t\t},
\t\t\t\t\t\t\t\t{
\t\t\t\t\t\t\t\t\teasing = "Linear",
\t\t\t\t\t\t\t\t\ttime = 1,
\t\t\t\t\t\t\t\t\tvalue = 0,
\t\t\t\t\t\t\t\t},
\t\t\t\t\t\t\t},
\t\t\t\t\t\t},
"""

# "particles": {"id": "steam"} splits emitters between base's two steam
# sprites. Chimneys sit at ~4 m (4.0 and 3.9 on two base and ported engines), cylinders under 1 m.
STEAM_CHIMNEY_Z = 2.5


def cmd_particles(v):
    """Give the exhaust a particle and let it fade.

    TF2 emitters carried a colour and nothing else; TF3 wants a `particleId`
    naming the sprite and an `alphaOverLifeTime` curve. The conversion leaves
    the id empty and adds no curve, so the exhaust draws as opaque untextured
    quads in whatever tint the author chose - one DMU's {0.2, 0.1, 0.4} came
    out as solid purple blobs.

    The author's colour is kept; only the missing parts are filled in.
    """
    cfg = v.cfg.get("particles", {})
    pid = cfg.get("id", "diesel_exhaust")
    alpha = cfg.get("alpha", 0.3)
    # the author's colour is kept unless the config overrides it: TF2 tints
    # that looked fine over its own smoke sprite can read as solid colour here
    color = cfg.get("color")

    for model in v.models():
        p = os.path.join(v.veh, model + ".mdl")
        lines = read(p).split("\n")
        recolored = 0
        if color:
            inside = False
            for i, l in enumerate(lines):
                if "colorOverLifeTime" in l:
                    inside = True
                elif inside:
                    m = re.match(r'(\t+)value = \{ [-0-9., ]+\},$', l)
                    if m:
                        lines[i] = "%svalue = { %s }," % (
                            m.group(1), ", ".join(str(c) for c in color))
                        recolored += 1
                        inside = False

        # a tint the author may never have seen: one steam engine's cylinder carried
        # { 0.7, 0.7, 0.5 } and puffed yellow on one side only
        inside = False
        for l in lines:
            if "colorOverLifeTime" in l:
                inside = True
            elif inside:
                m = re.match(r'\t+value = \{ ([-0-9., ]+?),? \},$', l)
                if m:
                    rgb = [float(c) for c in m.group(1).split(",")]
                    if max(rgb) - min(rgb) > 0.1:
                        print("  %s.mdl: emitter tinted %s - set particles.color "
                              "if it looks wrong" % (model, rgb))
                    inside = False

        hits = [i for i, l in enumerate(lines)
                if re.match(r'\t+particleId = "",$', l)]
        if not hits and not recolored:
            print("  %s.mdl: nothing to fill in" % model)
            continue
        used = collections.Counter()
        for i in reversed(hits):
            indent = re.match(r"(\t+)", lines[i]).group(1)
            outer = indent[:-1]
            start = next(j for j in range(i, -1, -1)
                         if lines[j].rstrip() == outer + "{")
            end = next(j for j in range(i, len(lines))
                       if lines[j] == outer + "},")
            this = pid
            if pid == "steam":
                # base's steam engines use two sprites: steam_chimney up top
                # and cylinder low down by the wheels (in base's steam engines).
                # TF2 had one sprite, so tell them apart by height.
                z = 0.0
                for l in lines[start:end]:
                    m = re.match(r'\t+position = \{ *[-0-9.e]+, *[-0-9.e]+, *([-0-9.e]+), *\},', l)
                    if m:
                        z = float(m.group(1))
                this = "steam_chimney" if z >= STEAM_CHIMNEY_Z else "cylinder"
            lines[i] = '%sparticleId = "%s",' % (indent, this)
            used[this] += 1
            # base's steam sprites fade by themselves and carry no curve
            if this in ("steam_chimney", "cylinder"):
                continue
            if not any("alphaOverLifeTime" in l for l in lines[start:end]):
                block = ALPHA_OVER_LIFETIME % alpha
                block = re.sub(r"(?m)^\t{6}", indent, block)
                block = re.sub(r"(?m)^\t{7}", indent + "\t", block)
                block = re.sub(r"(?m)^\t{8}", indent + "\t\t", block)
                block = re.sub(r"(?m)^\t{9}", indent + "\t\t\t", block)
                lines[start + 1:start + 1] = block.rstrip("\n").split("\n")
        write(p, "\n".join(lines))
        print("  %s.mdl: %d emitters -> %s, alpha %s, %d recoloured" % (
            model, len(hits), ", ".join("%s x%d" % kv for kv in sorted(used.items())),
            alpha, recolored))
