"""Vehicle icons drawn here instead of by the Model Editor (phase B-5)."""
import os
import time


def cmd_genicons(v):
    """`port.py <vehicle> genicons` with --engine native: the five icons of
    every model straight into content/<dir>/icons/."""
    from .icons import render_icons
    out = os.path.join(v.veh, "icons")
    n = 0
    for model in v.models():
        t = time.time()
        written = render_icons(os.path.join(v.veh, model + ".mdl"), out)
        n += len(written)
        print("  %-36s %d icons  %.0fs" % (model, len(written), time.time() - t))
    print("%d icons written into content/%s/icons/" % (n, v.content_dir))


def cmd_icons_native(v):
    print("icons: nothing to install - genicons --engine native wrote them in place")
