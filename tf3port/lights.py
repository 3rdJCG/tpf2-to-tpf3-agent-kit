"""lights: rebuild the head and tail lights that TF2 wrote as `*Lights`
index lists, which the conversion drops.
"""
import os
import re
import struct

from .common import read, write


ANIMATIONS = """\t\t\t\t\t\t\tanimations = {
\t\t\t\t\t\t\t\t%(slot)s_parts_off = {
\t\t\t\t\t\t\t\t\tparams = {
\t\t\t\t\t\t\t\t\t\tid = "::/vehicle/shared/ani/%(slot)s_parts_off.ani",
\t\t\t\t\t\t\t\t\t},
\t\t\t\t\t\t\t\t\ttype = "FILE_REF",
\t\t\t\t\t\t\t\t},
\t\t\t\t\t\t\t\t%(slot)s_parts_on = {
\t\t\t\t\t\t\t\t\tparams = {
\t\t\t\t\t\t\t\t\t\tid = "::/vehicle/shared/ani/%(slot)s_parts_on.ani",
\t\t\t\t\t\t\t\t\t},
\t\t\t\t\t\t\t\t\ttype = "FILE_REF",
\t\t\t\t\t\t\t\t},
\t\t\t\t\t\t\t},
"""

RED_LIGHTS = "::/vehicle/train/emissive/train_red_lights.mtl"


def mesh_center_x(v, mesh_path, transf):
    """x of a mesh's bounding-box centre after the node's 4x4 transform
    (row-vector convention, translation in 12..14).

    A TF3 .msh lists its vertex attributes with `offset` and `count` in bytes
    into the .blob beside it; positions are float32 triples."""
    msh = os.path.join(v.veh, mesh_path.replace("/", os.sep))
    text = read(msh)
    attr = text[text.index("vertexAttr"):]
    m = re.search(r'position = \{\s*count = (\d+),\s*numComp = 3,\s*offset = (\d+),',
                  attr)
    if not m:
        return transf[12]
    count, offset = int(m.group(1)), int(m.group(2))
    blob = open(msh + ".blob", "rb").read()[offset:offset + count]
    pts = struct.unpack("<%df" % (len(blob) // 4), blob)
    xs, ys, zs = pts[0::3], pts[1::3], pts[2::3]
    c = [(min(a) + max(a)) / 2 for a in (xs, ys, zs)]
    return c[0] * transf[0] + c[1] * transf[4] + c[2] * transf[8] + transf[12]


def add_tail_lights(v, model, txt):
    """Give a coach working tail lights it never had.

    Some TF2 coaches model the lamp housing but leave `backwardEndLights`
    empty - one coach mod's brake coaches do - so nothing ever lights up. The
    geometry is there, so we add a second node over the same mesh carrying the
    base game's red emissive material plus the direction animations.

    Which end the housing sits on decides the slot: a lamp at the front of the
    vehicle is the trailing end when the train runs backward, and vice versa.
    Coaches have no headlights, so only red is ever added.
    """
    meshes = v.cfg.get("tailLights", [])
    if not meshes:
        return txt, []
    added = []
    lines = txt.split("\n")
    # walk out from the mesh line to the node's own braces. A regex over the
    # whole file matches the enclosing children list first and loses the node
    # boundaries, so find them by indentation instead.
    targets = []
    for i, line in enumerate(lines):
        m = re.match(r'(\t+)mesh = "(msh/[^"]*/([a-z0-9_]+)\.msh)",$', line)
        if m and m.group(3) in meshes:
            targets.append((i, m.group(1), m.group(2)))

    for i, indent, mesh_path in reversed(targets):
        outer = indent[:-1]
        start = next(j for j in range(i, -1, -1)
                     if lines[j].rstrip() == outer + "{")
        end = next(j for j in range(i, len(lines))
                   if lines[j] == outer + "},")
        node = "\n".join(lines[start:end + 1])
        name = re.search(r'name = "([^"]+)"', node)
        transf = re.search(r'transf = \{([^}]*)\}', node)
        if not (name and transf) or name.group(1).endswith("_lit"):
            continue                         # our own copy; stay re-runnable
        if '"%s_lit"' % name.group(1) in txt:
            continue
        nums = [float(x) for x in transf.group(1).split(",") if x.strip()]
        # a lamp at the vehicle's front is the trailing end when the train
        # runs backward, and the other way round at the back. Where it sits
        # is the mesh's centre through the node's transform: one coach mod leaves
        # every node at the origin and bakes the position into the mesh, so
        # the node's translation alone put both of a coach's lamps at the front
        x = mesh_center_x(v, mesh_path, nums)
        slot = "front_backward" if x >= 0 else "back_forward"
        anim = ANIMATIONS % {"slot": slot}
        anim = re.sub(r"(?m)^\t{7}", indent, anim)
        anim = re.sub(r"(?m)^\t{8}", indent + "\t", anim)
        copy = ([outer + "{"] + anim.rstrip("\n").split("\n")
                + ['%smaterials = { "%s", },' % (indent, RED_LIGHTS),
                   '%smesh = "%s",' % (indent, mesh_path),
                   '%sname = "%s_lit",' % (indent, name.group(1)),
                   '%stransf = {%s},' % (indent, transf.group(1)),
                   outer + "},"])
        lines[end + 1:end + 1] = copy
        added.append((name.group(1), slot))

    return "\n".join(lines), list(reversed(added))


def cmd_lights(v):
    """TF2 named lights by node index in railVehicle.config; TF3 drives them
    from per-node animations and the conversion drops the old lists, so every
    light stays on at both ends in both directions."""
    if v.cfg.get("tailLights"):
        for model in v.models():
            p = os.path.join(v.veh, model + ".mdl")
            txt, added = add_tail_lights(v, model, read(p))
            if added:
                write(p, txt)
            print("%s.mdl: %d tail lights added" % (model, len(added)))
            for name, slot in added:
                print("    %-32s -> %s_parts_on/off" % (name, slot))
    if not v.lights:
        if not v.cfg.get("tailLights"):
            print("no light mapping in config - nothing to do")
        return
    for model in v.models():
        p = os.path.join(v.veh, model + ".mdl")
        lines = read(p).split("\n")
        done = []
        # walk out from the mesh line by indentation. A regex spanning the node
        # matches the enclosing children list first and loses the boundaries.
        targets = []
        for i, line in enumerate(lines):
            m = re.match(r'(\t+)mesh = "msh/[^"]*/([a-z0-9_]+)\.msh",$', line)
            if m and m.group(2) in v.lights:
                targets.append((i, m.group(1), m.group(2)))

        for i, indent, base in reversed(targets):
            outer = indent[:-1]
            start = next(j for j in range(i, -1, -1)
                         if lines[j].rstrip() == outer + "{")
            end = next(j for j in range(i, len(lines))
                       if lines[j] == outer + "},")
            # drop any animations block already in this node, then add ours
            node = lines[start:end + 1]
            keep, skip = [], False
            for l in node:
                if l == indent + "animations = {":
                    skip = True
                if skip:
                    if l == indent + "},":
                        skip = False
                    continue
                keep.append(l)
            slot = v.lights[base]
            anim = ANIMATIONS % {"slot": slot}
            anim = re.sub(r"(?m)^\t{7}", indent, anim)
            anim = re.sub(r"(?m)^\t{8}", indent + "\t", anim)
            lines[start:end + 1] = ([keep[0]] + anim.rstrip("\n").split("\n")
                                    + keep[1:])
            done.append((base, slot))
        done.reverse()

        write(p, "\n".join(lines))
        print("%s.mdl: %d light nodes" % (model, len(done)))
        for base, slot in done:
            print("    %-30s -> %s_parts_on/off" % (base, slot))
