"""A small software rasterizer in numpy, enough for vehicle icons.

No GPU, no window: triangles are binned by the size of their screen bounding
box, every candidate pixel of a bin is tested at once with edge functions,
and the nearest fragment per pixel wins (z-buffer by sorting). Opaque
surfaces and alpha-cut texels go through the depth test; glass (a
transparent material whose texel is mostly see-through) is blended over
what lies behind it. Supersampling gives the anti-aliased edges and the
alpha channel (coverage).
"""
import numpy as np

AMBIENT = 0.75
DIFFUSE = 0.9
GLASS_CUT = 0.5          # texel alpha below this is glass, above it solid
CBLEND_CHANNEL = 0
# Metal (red of the mga texture) mirrors its surroundings in the editor's
# pictures; a plain rasterizer has none, so metal takes this colour times its
# albedo. One value cannot suit every mod's metal maps; this one gives the
# lowest mean colour error over nine vehicles (stainless cars went from
# 46-61 to 25-38 out of 255 against no metal handling).
METAL_ENV = np.array([0.34, 0.37, 0.40], np.float32)


def _fragments(sx, sy, sz, w, h):
    """All covered pixel centres: -> tri index, pixel index, barycentrics (k,3), depth."""
    xmin = np.clip(np.floor(sx.min(1)), 0, w).astype(np.int64)
    xmax = np.clip(np.ceil(sx.max(1)), 0, w).astype(np.int64)
    ymin = np.clip(np.floor(sy.min(1)), 0, h).astype(np.int64)
    ymax = np.clip(np.ceil(sy.max(1)), 0, h).astype(np.int64)
    bw, bh = xmax - xmin, ymax - ymin
    area = (sx[:, 1] - sx[:, 0]) * (sy[:, 2] - sy[:, 0]) - (sx[:, 2] - sx[:, 0]) * (sy[:, 1] - sy[:, 0])
    ok = (bw > 0) & (bh > 0) & (np.abs(area) > 1e-12)
    # bin by the power of two above the box's width and height separately:
    # long thin triangles (rails, edges) would waste a square grid
    kx = np.ceil(np.log2(np.maximum(bw, 1))).astype(np.int64)
    ky = np.ceil(np.log2(np.maximum(bh, 1))).astype(np.int64)
    out_t, out_p, out_b, out_z = [], [], [], []
    keys = np.unique(np.stack([kx[ok], ky[ok]], 1), axis=0) if ok.any() else []
    for ex, ey in keys:
        gw, gh = 1 << int(ex), 1 << int(ey)
        sel = np.nonzero(ok & (kx == ex) & (ky == ey))[0]
        if len(sel):
            # chunk so a bin never holds more than ~8M candidates
            step = max(1, 8_000_000 // (gw * gh))
            for c in range(0, len(sel), step):
                t = sel[c:c + step]
                gx, gy = np.meshgrid(np.arange(gw), np.arange(gh))
                px = xmin[t, None] + gx.ravel()[None, :]
                py = ymin[t, None] + gy.ravel()[None, :]
                cx, cy = px + 0.5, py + 0.5
                x0, x1, x2 = sx[t, 0, None], sx[t, 1, None], sx[t, 2, None]
                y0, y1, y2 = sy[t, 0, None], sy[t, 1, None], sy[t, 2, None]
                a = area[t, None]
                w0 = ((x1 - cx) * (y2 - cy) - (x2 - cx) * (y1 - cy)) / a
                w1 = ((x2 - cx) * (y0 - cy) - (x0 - cx) * (y2 - cy)) / a
                w2 = 1.0 - w0 - w1
                inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0) & (px < xmax[t, None]) & (py < ymax[t, None]) \
                    & (px < w) & (py < h)
                ti, ci = np.nonzero(inside)
                if not len(ti):
                    continue
                tt = t[ti]
                bary = np.stack([w0[ti, ci], w1[ti, ci], w2[ti, ci]], 1)
                out_t.append(tt)
                out_p.append(py[ti, ci] * w + px[ti, ci])
                out_b.append(bary)
                out_z.append((bary * sz[tt]).sum(1))
    if not out_t:
        return (np.zeros(0, np.int64),) * 2 + (np.zeros((0, 3)), np.zeros(0))
    return np.concatenate(out_t), np.concatenate(out_p), np.concatenate(out_b), np.concatenate(out_z)


def _sample(tex, uv):
    h, w = tex.shape[:2]
    x = np.floor(np.mod(uv[:, 0], 1.0) * w).astype(np.int64) % w
    y = np.floor(np.mod(uv[:, 1], 1.0) * h).astype(np.int64) % h
    return tex[y, x]


def _nearest(pix, z, keep):
    """Index (into the fragment arrays) of the nearest kept fragment per pixel."""
    idx = np.nonzero(keep)[0]
    order = idx[np.lexsort((z[idx], pix[idx]))]
    first = np.ones(len(order), bool)
    first[1:] = pix[order][1:] != pix[order][:-1]
    return order[first]


def render(scene, project, w, h, light, ss=3):
    """project(points (n,3)) -> (x px, y px, depth) in a w*ss x h*ss image.
    -> RGBA uint8 (h, w, 4) and the cblend mask uint8 (h, w)."""
    W, H = w * ss, h * ss
    n = len(scene.pos)
    flat = scene.pos.reshape(-1, 3)
    x, y, z = project(flat)
    sx, sy, sz = (a.reshape(n, 3) for a in (x * ss, y * ss, z))
    tri, pix, bary, depth = _fragments(sx, sy, sz, W, H)

    mats = scene.materials
    mid = scene.mat[tri]
    uv = (bary[:, :, None] * scene.uv[tri]).sum(1)
    albedo = np.ones((len(tri), 4), np.float32) * 0.6
    albedo[:, 3] = 1
    for i, m in enumerate(mats):
        sel = mid == i
        if m.texture is not None and sel.any():
            albedo[sel] = _sample(m.texture, uv[sel])
    transparent = np.array([m.transparent for m in mats], bool)[mid] if mats else np.zeros(len(tri), bool)
    emissive = np.array([m.emissive for m in mats], bool)[mid] if mats else np.zeros(len(tri), bool)
    # the recolourable paint: 1 - red of a CBLEND material's cblend/dirt/rust
    # texture (red marks what keeps its own colour); matches the editor's
    # masks to 5.8/255 on average. Without that texture, the whole material
    cblend = np.zeros(len(tri), np.float32)
    for i, m in enumerate(mats):
        sel = mid == i
        if m.cblend and sel.any():
            cblend[sel] = (1.0 - _sample(m.cblend_tex, uv[sel])[:, CBLEND_CHANNEL]) if m.cblend_tex is not None else 1.0

    nrm = (bary[:, :, None] * scene.nrm[tri]).sum(1)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
    lambert = np.abs(nrm @ np.asarray(light, np.float64))       # two-sided
    shade = np.where(emissive, 1.0, AMBIENT + DIFFUSE * lambert)
    metal = np.zeros(len(tri), np.float32)
    for i, m in enumerate(mats):
        sel = mid == i
        if m.mga_tex is not None and sel.any():
            metal[sel] = _sample(m.mga_tex, uv[sel])[:, 0]
    lit = albedo[:, :3] * shade[:, None]
    mirrored = albedo[:, :3] * METAL_ENV[None, :] * (0.6 + 0.4 * shade[:, None])
    rgb = np.clip(lit * (1 - metal[:, None]) + mirrored * metal[:, None], 0, 1)

    solid = ~transparent | (albedo[:, 3] >= GLASS_CUT)
    color = np.zeros((W * H, 3), np.float32)
    cover = np.zeros(W * H, np.float32)
    mask = np.zeros(W * H, np.float32)
    zbuf = np.full(W * H, np.inf)
    win = _nearest(pix, depth, solid)
    color[pix[win]] = rgb[win]
    cover[pix[win]] = 1
    mask[pix[win]] = cblend[win]
    zbuf[pix[win]] = depth[win]

    glass = transparent & ~solid & (albedo[:, 3] > 0.02)
    gwin = _nearest(pix, depth, glass)
    gwin = gwin[depth[gwin] < zbuf[pix[gwin]]]
    if len(gwin):
        a = albedo[gwin, 3:4]
        p = pix[gwin]
        color[p] = color[p] * (1 - a) * cover[p, None] + rgb[gwin] * a
        cover[p] = np.maximum(cover[p], a[:, 0])
        # under glass with nothing behind it the colour stands alone
        lone = cover[p] <= a[:, 0] + 1e-6
        color[p[lone]] = rgb[gwin][lone]

    def down(a):
        # a is (H, W, ...) -> (h, w, ...), averaging each ss x ss block
        return a.reshape(h, ss, w, ss, *a.shape[2:]).mean((1, 3))

    color = color.reshape(H, W, 3)
    cover = cover.reshape(H, W)
    alpha = down(cover)
    premul = down(color * cover[..., None])
    rgb_out = premul / np.maximum(alpha[..., None], 1e-6)
    out = np.dstack([np.clip(rgb_out, 0, 1), alpha])
    return (out * 255 + 0.5).astype(np.uint8), (np.clip(down(mask.reshape(H, W)), 0, 1) * 255 + 0.5).astype(np.uint8)
