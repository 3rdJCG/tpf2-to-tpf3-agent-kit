"""icons: install the icons the Model Editor's Bulk Generate rendered."""
import os
import shutil

from .common import ICON_SUFFIXES
from .paths import SCREENSHOTS


def cmd_icons(v):
    dst = os.path.join(v.veh, "icons")
    os.makedirs(dst, exist_ok=True)
    copied, missing = 0, []
    for model in v.models():
        for suffix in ICON_SUFFIXES:
            fn = model + suffix
            src = os.path.join(SCREENSHOTS, fn)
            if not os.path.exists(src):
                missing.append(fn)
                continue
            shutil.copy2(src, os.path.join(dst, fn))
            copied += 1
    print("%d icons installed into content/%s/icons/" % (copied, v.content_dir))
    if missing:
        print("missing %d - run Icons > Bulk Generate in the Model Editor first"
              % len(missing))
