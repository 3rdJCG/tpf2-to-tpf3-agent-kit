"""names: the names the purchase menu shows, in Japanese and English.

Every vehicle (`description.name`) and consist (`name`) gets a translation
key of its own, `PORTNAME_<modId>_<file>`, and strings.json gets the text:

  - `"names"` in the vehicle config, if it names the file:
        "names": {"dmu.mdl":    {"ja": "...", "en": "Railway DMU Class 1"},
                  "dmu.mu.lua": {"ja": "...", "en": "Class 1 2 cars"}}
  - otherwise the name the mod came with.

`name_prefix` in local_settings.json goes in front of every name, so ports
can be told apart from other vehicles in the menu at a glance.

The names the mod came with are kept in _metadata/names.json the first time
this runs, so a re-run (or a changed prefix) starts from them, not from its
own output. Runs after `strings` and `consists`, which rewrite strings.json
and the consists.
"""
import json
import os
import re

from .common import read, write
from .paths import local_setting

STORE = "names.json"
EXPR = r'(_\(\s*"(?:[^"\\]|\\.)*"\s*\)|"(?:[^"\\]|\\.)*")'


def unquote(s):
    return re.sub(r'\\(.)', lambda m: {"n": " "}.get(m.group(1), m.group(1)), s)


def resolve(expr, langs):
    """{"ja": .., "en": ..} for a name expression, through strings.json."""
    m = re.match(r'_\(\s*"((?:[^"\\]|\\.)*)"\s*\)$', expr)
    if m:
        key = unquote(m.group(1))
        ja = langs.get("ja", {}).get(key)
        en = langs.get("en", {}).get(key)
        ja, en = ja or en or key, en or ja or key
    else:
        ja = en = unquote(expr[1:-1])
    flat = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731
    return {"ja": flat(ja), "en": flat(en)}


def name_span(text, consist):
    """(start, end) of the name expression, or None."""
    if consist:
        for m in re.finditer(r'(?m)^[ \t]*name = ' + EXPR, text):
            if not m.group(1).endswith('.mdl"'):
                return m.start(1), m.end(1)
        return None
    d = text.find("description = {")
    if d < 0:
        return None
    m = re.compile(r'\n[ \t]+name = ' + EXPR).search(text, d)
    return (m.start(1), m.end(1)) if m else None


def cmd_names(v):
    prefix = local_setting("name_prefix", "")
    overrides = v.cfg.get("names", {})
    sj = os.path.join(v.dst, "strings.json")
    langs = json.load(open(sj, encoding="utf-8")) if os.path.exists(sj) else {}
    store_p = os.path.join(v.dst, "_metadata", STORE)
    store = json.load(open(store_p, encoding="utf-8")) if os.path.exists(store_p) else {}

    files = sorted(f for f in os.listdir(v.veh) if f.endswith((".mdl", ".mu.lua")))
    unknown = set(overrides) - set(files)
    for f in sorted(unknown):
        print("  names: no %s in %s - ignored" % (f, v.veh))
    n = renamed = 0
    for f in files:
        p = os.path.join(v.veh, f)
        text = read(p)
        consist = f.endswith(".mu.lua")
        if not consist and "transportVehicle" not in text:
            continue
        span = name_span(text, consist)
        if span is None:
            print("  %s: no name found" % f)
            continue
        key = "PORTNAME_%s_%s" % (v.mod_id, re.sub(r"[^a-z0-9_]+", "_", f.lower()))
        expr = text[span[0]:span[1]]
        if key not in expr or f not in store:
            got = resolve(expr, langs)
            if key in expr and prefix:
                # our own output with the record lost: take the prefix off
                got = {k: s[len(prefix):] if s.startswith(prefix) else s
                       for k, s in got.items()}
            store[f] = got
        name = overrides.get(f) or store[f]
        if isinstance(name, list):
            name = {"ja": name[0], "en": name[1]}
        if f in overrides:
            renamed += 1
        for lang in ("ja", "en"):
            text_ = name.get(lang) or name.get("en") or name.get("ja")
            langs.setdefault(lang, {})[key] = prefix + text_
        new = text[:span[0]] + '_("%s")' % key + text[span[1]:]
        if new != text:
            write(p, new)
        n += 1
    write(sj, json.dumps(langs, indent="\t", ensure_ascii=False) + "\n")
    write(store_p, json.dumps(store, indent=4, ensure_ascii=False) + "\n")
    print("names: %d named, %d from the config, prefix %r" % (n, renamed, prefix))
