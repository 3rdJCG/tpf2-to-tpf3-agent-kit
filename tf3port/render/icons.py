"""Vehicle icons without the Model Editor (its Icons > Bulk Generate).

The editor's settings (model_editor_settings_v13.lua, screenshotOptions)
say how it frames them, and its output on 31 vehicles confirms it:

- side icons (`_icon_small@2x`, `_icon20@2x`): an orthographic side view at
  sideConfig.pixelsPerMeter (8) x upscaleFactor (2) = 16 px/m, standing on
  the editor's track stage (model_editor/stage/stage_track_simple.mdl, a
  4 m piece tiled along the vehicle). The width is the boundingInfo length,
  the height fixed: 56 or fixedHeight 20 px, doubled. The colours are then
  pushed in HSV: saturation ** satExp (0.7), value ** valExp (0.85); the
  20 px one uses fixedSatExp / fixedValExp (0.6, 0.8).
- `_cblend` variants: white where a CBLEND material (the paint the game
  recolours) is visible.
- `_store`: a perspective view, the same camera for every vehicle
  (STORE_CAMERA, fitted to the editor's pictures; its settings say
  view3d.angle 135, fovY 30, which in our axes is azimuth -20 at 52.5 m),
  cropped to the content plus 8 px.

This is a plain rasterizer (raster.py), not the game's renderer: shapes,
framing and textures match, lighting is simpler.
"""
import numpy as np

from . import raster, scene as S

TRACK = "::/model_editor/stage/stage_track_simple.mdl"
TRACK_TILE = 4.0
PIXELS_PER_METER = 16.0
LIGHT = np.array([0.35, -0.55, 0.75])
LIGHT = LIGHT / np.linalg.norm(LIGHT)

SIDE_ICONS = (
    # suffix, height, satExp, valExp
    ("_icon_small@2x", 112, 0.7, 0.85),
    ("_icon20@2x", 40, 0.6, 0.8),
)


def _translate(x):
    m = np.eye(4)
    m[0, 3] = x
    return m


def with_track(model, lo_x, hi_x):
    tiles = []
    k0 = int(np.floor((lo_x - TRACK_TILE) / TRACK_TILE))
    k1 = int(np.ceil((hi_x + TRACK_TILE) / TRACK_TILE))
    for k in range(k0, k1 + 1):
        tiles.append(S.Scene(TRACK, transf=_translate(k * TRACK_TILE)))
    return S.merge([model] + tiles)


def side_view(model, points, height, side=1, pitch=0.0, ppm=PIXELS_PER_METER):
    """-> (project, w, h) for an orthographic side view, looking down by
    `pitch` degrees, with the lowest of `points` (the track) on the bottom
    edge. side=+1 looks from -y, -1 from +y."""
    bb = model.model["boundingInfo"]
    lo, hi = np.array(bb["bbMin"], float), np.array(bb["bbMax"], float)
    scale = ppm * height / 112.0
    w = int(2 * round((hi[0] - lo[0]) * scale / 2))
    cx = (lo[0] + hi[0]) / 2
    c, s = np.cos(np.radians(pitch)), np.sin(np.radians(pitch))

    def up(q):
        return q[:, 2] * c + side * q[:, 1] * s

    floor = up(points).min()

    def project(q):
        x = w / 2 - side * (q[:, 0] - cx) * scale
        y = height - (up(q) - floor) * scale
        return x, y, side * q[:, 1] * c - q[:, 2] * s
    return project, w, height


def hsv_push(rgba, sat_exp, val_exp):
    """The editor's colour tweak: s ** sat_exp, v ** val_exp in HSV."""
    rgb = rgba[..., :3].astype(np.float64) / 255.0
    mx = rgb.max(-1)
    mn = rgb.min(-1)
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-9), 0)
    v2 = mx ** val_exp
    s2 = s ** sat_exp
    # keep hue: scale each channel's distance from max
    with np.errstate(invalid="ignore", divide="ignore"):
        k = np.where(s > 0, s2 / s, 0)[..., None]
    out = mx[..., None] - (mx[..., None] - rgb) * k
    out = out * np.where(mx > 0, v2 / np.maximum(mx, 1e-9), 0)[..., None]
    res = rgba.copy()
    res[..., :3] = np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8)
    return res


def perspective_view(model, azimuth, elevation, distance, fov_y, focal_px):
    """-> project for a camera `distance` m from the bounding box centre, at
    `azimuth` degrees around z (0 = +x, the front) and `elevation` above the
    horizon, focal length in pixels; the image centre is (0, 0) - crop later."""
    bb = model.model["boundingInfo"]
    centre = (np.array(bb["bbMin"], float) + np.array(bb["bbMax"], float)) / 2
    a, e = np.radians(azimuth), np.radians(elevation)
    eye = centre + distance * np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
    fwd = centre - eye
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, [0, 0, 1.0])
    right /= np.linalg.norm(right)
    upv = np.cross(right, fwd)

    def project(q):
        d = q - eye
        zc = d @ fwd
        return focal_px * (d @ right) / zc, -focal_px * (d @ upv) / zc, zc
    return project


def crop(rgba, pad=8):
    """The editor's store image: the content's bounding box plus `pad` px."""
    ys, xs = np.nonzero(rgba[..., 3] > 0)
    if not len(ys):
        return rgba
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, rgba.shape[0])
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, rgba.shape[1])
    return rgba[y0:y1, x0:x1]


# The store picture: one fixed camera for every vehicle, not fitted to it,
# then cropped to the content plus 8 px. Fitted to the editor's pictures
# (silhouette IoU 0.98-0.99 on five vehicles of 8-21 m, sizes within 7 px).
STORE_CAMERA = {"azimuth": -20.0, "elevation": 0.6, "distance": 52.5, "focal_px": 4890.0}


def store_image(model):
    proj = perspective_view(model, STORE_CAMERA["azimuth"], STORE_CAMERA["elevation"],
                            STORE_CAMERA["distance"], 30, STORE_CAMERA["focal_px"])
    x, y, _ = proj(model.pos.reshape(-1, 3))
    # some mods have stray vertices far away (hidden helpers); frame the bulk
    x0, x1 = np.percentile(x, [0.01, 99.99]) + (-10, 10)
    y0, y1 = np.percentile(y, [0.01, 99.99]) + (-10, 10)
    x0, y0 = np.floor(x0), np.floor(y0)
    x1, y1 = np.ceil(x1), np.ceil(y1)
    w, h = int(x1 - x0), int(y1 - y0)

    def project(q):
        a, b, c = proj(q)
        return a - x0, b - y0, c
    # no HSV push here: the editor's store pictures are closer without it
    img, _ = raster.render(model, project, w, h, LIGHT, ss=2)
    return crop(img)


def side_images(model):
    """-> {suffix: RGBA} for the side icons and {suffix: L} for their masks."""
    bb = model.model["boundingInfo"]
    full = with_track(model, bb["bbMin"][0], bb["bbMax"][0])
    points = full.pos.reshape(-1, 3)
    out = {}
    for suffix, height, sat_exp, val_exp in SIDE_ICONS:
        project, w, h = side_view(model, points, height)
        img, mask = raster.render(full, project, w, h, LIGHT)
        out[suffix] = hsv_push(img, sat_exp, val_exp)
        out[suffix.replace("@2x", "_cblend@2x")] = mask
    return out


def render_icons(mdl_path, out_dir):
    """Write the five icons for one model next to the editor's names:
    <model>_icon20@2x.tga ... <model>_store.tga. -> paths written."""
    from PIL import Image
    import os
    name = os.path.splitext(os.path.basename(mdl_path))[0]
    model = S.Scene(mdl_path)
    images = side_images(model)
    images["_store"] = store_image(model)
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for suffix, img in images.items():
        path = os.path.join(out_dir, name + suffix + ".tga")
        Image.fromarray(img, "L" if img.ndim == 2 else "RGBA").save(path)
        written.append(path)
    return written
