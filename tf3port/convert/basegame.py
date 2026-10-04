"""Read files out of the installed game's base/content.

The conversion follows definitions that ship with TF3 (material types,
material properties). They are Urban Games' files, so this tool does not
carry copies: it reads them from the player's own installation each run.

base/content/**/*.zip start with Urban Games' own "UG" signature in place of
"PK" on the first local header only; the rest of the archive is a standard
zip, so patching those two bytes in memory is enough.
"""
import io
import os
import zipfile

from ..paths import TF3_BASE

_zips = {}


def open_zip(rel):
    """base/content/<rel> (e.g. "rendering/properties.zip") as a ZipFile."""
    if rel not in _zips:
        path = os.path.join(TF3_BASE, *rel.split("/"))
        with open(path, "rb") as f:
            data = bytearray(f.read())
        if data[:2] == b"UG":
            data[:2] = b"PK"
        _zips[rel] = zipfile.ZipFile(io.BytesIO(bytes(data)))
    return _zips[rel]


def read_text(rel):
    """A loose file under base/content, as text."""
    with open(os.path.join(TF3_BASE, *rel.split("/")), encoding="utf-8-sig") as f:
        return f.read()


def list_dir(rel):
    d = os.path.join(TF3_BASE, *rel.split("/"))
    return sorted(os.listdir(d)) if os.path.isdir(d) else []
