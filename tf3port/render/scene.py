"""A converted TF3 model as flat arrays of triangles, for render/raster.py.

A model's first LOD is a node tree; each node has a 4x4 `transf`
(column-major: x' = c0*x + c1*y + c2*z + t, t in elements 13-15), and may
carry a mesh with one material per submesh. Meshes index every vertex
attribute separately (OBJ-like): each submesh has its own uint32 index list
per attribute into that attribute's array. Paths in a .mdl are relative to
its folder; texture paths in a .mtl relative to the .mtl's folder; "::/"
means the game's base (read from the installed game).
"""
import io
import os

import numpy as np

from ..convert import luadata, luaenv, basegame

ALBEDO_SAMPLERS = ("albedoTex", "albedoOpacityTex", "emissiveTex")
CBLEND_SAMPLERS = ("cblendDirtRustTex", "cblendTex")
MGA_SAMPLERS = ("metalGlossAoTex",)


class Material(object):
    def __init__(self, kind, texture, transparent, cblend, emissive, cblend_tex=None, mga_tex=None):
        self.kind = kind
        self.mga_tex = mga_tex          # metal / gloss / ao, or None
        self.cblend_tex = cblend_tex    # where the paint is recoloured, or None
        self.texture = texture          # HxWx4 float32 0..1, or None
        self.transparent = transparent
        self.cblend = cblend            # the paint the game recolours
        self.emissive = emissive


def _matrix(t):
    return np.array(t, dtype=np.float64).reshape(4, 4).T


def join(base_dir, ref):
    """ref as seen from base_dir. A ref starting with "::/" or "/" (the
    latter in the game's own files) is the game's base; base_dir itself may
    be "::/..." for a model inside the game."""
    if ref.startswith("::") or ref.startswith("/"):
        return "::/" + ref.split("::", 1)[-1].lstrip("/")
    if base_dir.startswith("::"):
        parts = []
        for part in (base_dir.split("::", 1)[1].strip("/") + "/" + ref).split("/"):
            if part == "..":
                parts.pop()
            elif part not in ("", "."):
                parts.append(part)
        return "::/" + "/".join(parts)
    return os.path.normpath(os.path.join(base_dir, *ref.split("/")))


def dirname(ref):
    return ref.rsplit("/", 1)[0] if ref.startswith("::") else os.path.dirname(ref)


def read_ref(ref, base_dir=""):
    """Bytes of a file a model refers to: "::/..." from the game, else
    relative to base_dir."""
    ref = join(base_dir, ref) if base_dir else ref
    if ref.startswith("::"):
        key = ref.split("::", 1)[1].lstrip("/")
        hit = luaenv.resource_index().get(key)
        if hit:
            return basegame.open_zip(hit[0]).read(hit[1])
        with open(os.path.join(basegame.TF3_BASE, *key.split("/")), "rb") as f:
            return f.read()
    with open(ref, "rb") as f:
        return f.read()


_textures = {}


def load_texture(ref, base_dir):
    """RGBA float32, rows top to bottom as TF3 samples them (v = 0 at the
    first row for .dds; a .tga is stored bottom-up, so PIL's top-down image
    is flipped to match)."""
    from PIL import Image
    key = join(base_dir, ref)
    if key not in _textures:
        try:
            im = Image.open(io.BytesIO(read_ref(key))).convert("RGBA")
            a = np.asarray(im, dtype=np.float32) / 255.0
            if ref.lower().endswith(".tga"):
                a = a[::-1]
            _textures[key] = np.ascontiguousarray(a)
        except (OSError, ValueError):
            _textures[key] = None
    return _textures[key]


_materials = {}


def load_material(ref, model_dir):
    path = join(model_dir, ref)
    if path in _materials:
        return _materials[path]
    try:
        mtl = luadata.parse(read_ref(path).decode("utf-8-sig"))
    except (OSError, KeyError, luadata.LuaSyntaxError):
        mtl = {"type": "PHYSICAL", "params": {}}
    mat_dir = dirname(path)
    kind = mtl.get("type", "")
    tex = ctex = mga = None
    for prop in mtl.get("params", {}).values():
        for name, sampler in (prop.get("fragmentSamplers") or {}).items():
            if name in ALBEDO_SAMPLERS and tex is None and "fileName" in sampler:
                tex = load_texture(sampler["fileName"], mat_dir)
            if name in CBLEND_SAMPLERS and ctex is None and "fileName" in sampler:
                ctex = load_texture(sampler["fileName"], mat_dir)
            if name in MGA_SAMPLERS and mga is None and "fileName" in sampler:
                mga = load_texture(sampler["fileName"], mat_dir)
    m = Material(kind, tex, "TRANSPARENT" in kind, "CBLEND" in kind, kind.startswith("EMISSIVE"), ctex, mga)
    _materials[path] = m
    return m


def load_mesh(path):
    msh = luadata.parse(read_ref(path).decode("utf-8-sig"))
    blob = read_ref(path + ".blob")

    def floats(entry):
        a = np.frombuffer(blob, dtype=np.float32, count=entry["count"] // 4, offset=entry["offset"])
        return a.reshape(-1, entry["numComp"])

    va = msh["vertexAttr"]
    attrs = {k: floats(va[k]) for k in ("position", "normal", "uv0") if k in va}
    subs = []
    for sm in msh["subMeshes"]:
        idx = {}
        for k, e in sm["indices"].items():
            idx[k] = np.frombuffer(blob, dtype=np.uint32, count=e["count"] // 4, offset=e["offset"])
        subs.append(idx)
    return attrs, subs


class Scene(object):
    """Triangles of one model: corners (N,3,3) world positions, normals
    (N,3,3), uvs (N,3,2), and material index per triangle."""

    def __init__(self, mdl_path, lod=0, transf=None):
        """mdl_path: a file, or "::/..." for one of the game's models."""
        self.dir = dirname(mdl_path)
        self.model = luadata.parse(read_ref(mdl_path).decode("utf-8-sig"))
        self.materials = []
        self._mat_index = {}
        pos, nrm, uv, mat = [], [], [], []
        node = self.model["lods"][lod]["node"]
        self._walk(node, np.eye(4) if transf is None else transf, pos, nrm, uv, mat)
        if pos:
            self.pos = np.concatenate(pos)
            self.nrm = np.concatenate(nrm)
            self.uv = np.concatenate(uv)
            self.mat = np.concatenate(mat)
            if transf is None:          # the box is in the model's own frame
                self._drop_outside()
        else:
            self.pos = np.zeros((0, 3, 3))
            self.nrm = np.zeros((0, 3, 3))
            self.uv = np.zeros((0, 3, 2))
            self.mat = np.zeros(0, dtype=np.int32)

    # How far past boundingInfo geometry may reach and still be drawn. Raised
    # pantographs stand up to ~1.7 m above a box made with them folded.
    # Light beams (EMISSIVE cones 100 m long) and parts that the game shrinks
    # to nothing with the shared *_parts_off animations sit far outside the
    # box; the editor's icons do not show them, and one stray vertex at 1e8 m
    # would make a perspective picture gigabytes large.
    BOUNDS_MARGIN = 3.0

    def _drop_outside(self):
        bb = self.model.get("boundingInfo")
        if not bb:
            return
        lo = np.array(bb["bbMin"], float) - self.BOUNDS_MARGIN
        hi = np.array(bb["bbMax"], float) + self.BOUNDS_MARGIN
        keep = ~((self.pos < lo) | (self.pos > hi)).any(axis=(1, 2))
        self.pos, self.nrm, self.uv, self.mat = self.pos[keep], self.nrm[keep], self.uv[keep], self.mat[keep]

    def _material(self, ref):
        if ref not in self._mat_index:
            self._mat_index[ref] = len(self.materials)
            self.materials.append(load_material(ref, self.dir))
        return self._mat_index[ref]

    def _walk(self, node, parent, pos, nrm, uv, mat):
        m = parent @ _matrix(node.get("transf", (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)))
        mesh = node.get("mesh")
        if isinstance(mesh, str) and mesh.endswith(".msh"):
            path = join(self.dir, mesh)
            if path.startswith("::") or os.path.exists(path):
                attrs, subs = load_mesh(path)
                rot = m[:3, :3]
                # normals go through the inverse transpose (non-uniform scale)
                try:
                    nmat = np.linalg.inv(rot).T
                except np.linalg.LinAlgError:
                    nmat = rot
                p = attrs["position"] @ rot.T + m[:3, 3]
                n = attrs.get("normal", np.zeros((1, 3))) @ nmat.T
                t = attrs.get("uv0", np.zeros((1, 2)))
                mats = node.get("materials") or []
                for i, idx in enumerate(subs):
                    if "position" not in idx:
                        continue
                    tri = idx["position"].reshape(-1, 3)
                    pos.append(p[tri])
                    nrm.append(n[idx["normal"].reshape(-1, 3)] if "normal" in idx else np.zeros(pos[-1].shape))
                    uv.append(t[idx["uv0"].reshape(-1, 3)] if "uv0" in idx else np.zeros(pos[-1].shape[:2] + (2,)))
                    ref = mats[i] if i < len(mats) else (mats[-1] if mats else "")
                    mat.append(np.full(len(tri), self._material(ref) if ref else self._material("::/none"), dtype=np.int32))
        for child in node.get("children", []) or []:
            self._walk(child, m, pos, nrm, uv, mat)


def merge(scenes):
    """Several scenes as a new one (material indices shifted); the first
    supplies the model data (boundingInfo ...). The inputs are not changed."""
    import copy
    out = copy.copy(scenes[0])
    out.materials = list(scenes[0].materials)
    pos, nrm, uv, mat = [out.pos], [out.nrm], [out.uv], [out.mat]
    for other in scenes[1:]:
        pos.append(other.pos)
        nrm.append(other.nrm)
        uv.append(other.uv)
        mat.append(other.mat + len(out.materials))
        out.materials = out.materials + other.materials
    out.pos, out.nrm = np.concatenate(pos), np.concatenate(nrm)
    out.uv, out.mat = np.concatenate(uv), np.concatenate(mat)
    return out
