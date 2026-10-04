"""Compare tf3port.render's icons with the Model Editor's in staging.

    python port.py compare-icons [vehicle ...] [--all-models]

For each vehicle (default: every config), draws the icons of its first model
(or all with --all-models) into a temporary folder and compares each with the
editor's in content/<dir>/icons/: size, silhouette IoU (alpha > 127), and for
colour icons the mean colour difference where both are opaque (0-255); for
the _cblend masks the mean difference. Run it after a `port.py <v> all
--engine editor`, which leaves the editor's icons in place.
"""
import os
import sys
import tempfile


import numpy as np
from PIL import Image

from tf3port.common import Vehicle, vehicle_names
from tf3port.render.icons import render_icons


def score(ours, theirs):
    a = np.asarray(Image.open(ours))
    b = np.asarray(Image.open(theirs))
    size_ok = a.shape == b.shape
    h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    a, b = a[:h, :w].astype(float), b[:h, :w].astype(float)
    if a.ndim == 2:
        return size_ok, None, np.abs(a - b).mean()
    ma, mb = a[..., 3] > 127, b[..., 3] > 127
    iou = (ma & mb).sum() / max(1, (ma | mb).sum())
    both = (a[..., 3] > 250) & (b[..., 3] > 250)
    err = np.abs(a[both][:, :3] - b[both][:, :3]).mean() if both.any() else float("nan")
    return size_ok, iou, err


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    every = "--all-models" in sys.argv
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for name in args or vehicle_names():
            v = Vehicle(name)
            models = v.models() if every else v.models()[:1]
            for m in models:
                ref_dir = os.path.join(v.veh, "icons")
                if not os.path.exists(os.path.join(ref_dir, m + "_store.tga")):
                    print("%-14s %-30s no editor icons to compare" % (name, m))
                    continue
                for p in render_icons(os.path.join(v.veh, m + ".mdl"), tmp):
                    suffix = os.path.basename(p)[len(m):-4]
                    size_ok, iou, err = score(p, os.path.join(ref_dir, os.path.basename(p)))
                    rows.append((suffix, size_ok, iou, err))
                    print("%-14s %-30s %-22s size %-3s IoU %s  diff %.1f" % (
                        name, m[:30], suffix, "ok" if size_ok else "NO",
                        "%.3f" % iou if iou is not None else "  -  ", err), flush=True)
    print("\nsummary (per icon kind): size ok / IoU mean, min / colour or mask diff mean")
    for suffix in sorted(set(r[0] for r in rows)):
        rs = [r for r in rows if r[0] == suffix]
        ious = [r[2] for r in rs if r[2] is not None]
        print("  %-22s %d/%d  %s  %.1f" % (
            suffix, sum(r[1] for r in rs), len(rs),
            "%.3f, %.3f" % (np.mean(ious), np.min(ious)) if ious else "  -  ",
            np.nanmean([r[3] for r in rs])))


if __name__ == "__main__":
    main()
