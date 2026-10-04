"""strings and consists: translated names and multiple-unit rules."""
import json
import os
import re

from .build import BUILD_STRINGS, lift_strings, model_ref
from .common import read, tf3_name, write
from .paths import WORKSHOP


LUA_ESCAPES = {"\\n": "\n", "\\t": "\t", '\\"': '"', "\\\\": "\\"}


def lua_string_expr(expr):
    """Flatten a Lua string expression like `"a"..lb.."b"` into text.

    Mod authors build multi-line descriptions this way, with a local `lb`
    holding a newline."""
    out = []
    for lit, ident in re.findall(r'"((?:[^"\\]|\\.)*)"|\b(lb)\b', expr):
        if ident:
            out.append("\n")
            continue
        for k, vv in LUA_ESCAPES.items():
            lit = lit.replace(k, vv)
        out.append(lit)
    return "".join(out)


def cmd_strings(v):
    """TF2 kept translations in strings.lua; TF3 wants strings.json at the mod
    root. Same shape - a table per language - so this is a transcription.

    Keys the models use but this mod does not define are looked up in the
    other installed workshop mods, like borrowed textures: one EMU mod shows
    cars from a sibling mod whose names live in that mod's strings.lua, and
    the game displayed the raw key (Author_Car_1043_name)."""
    src = os.path.join(v.src, "strings.lua")
    langs = parse_strings_lua(src) if os.path.exists(src) else {}
    for lang, entries in sorted(langs.items()):
        print("  %-6s %d strings" % (lang, len(entries)))
    # the non-ASCII names and descriptions build lifted out of the models
    lifted = os.path.join(v.dst, "_metadata", BUILD_STRINGS)
    if os.path.exists(lifted):
        table = json.load(open(lifted, encoding="utf-8"))
        for lang in sorted(set(langs) | {"en", "ja"}):
            for k, text in table.items():
                langs.setdefault(lang, {}).setdefault(k, text)
        print("  %d texts lifted out of the models by build" % len(table))

    used = set()
    for f in os.listdir(v.veh):
        if f.endswith((".mdl", ".mu.lua")):
            used.update(re.findall(r'_\("([^"]+)"\)', read(os.path.join(v.veh, f))))
    defined = set(k for e in langs.values() for k in e)
    want = sorted(k for k in used - defined if re.match(r"^[A-Za-z0-9_.-]+$", k))
    if want:
        got = borrowed_strings(want)
        for lang, entries in got.items():
            langs.setdefault(lang, {}).update(entries)
        found = set(k for e in got.values() for k in e)
        # Defined nowhere (a key like Author_Car_1043_name): the original
        # showed the raw key in TF2 too. A readable name made from the key
        # beats that.
        made = {k: readable_key(k) for k in sorted(set(want) - found)}
        for lang in sorted(set(langs) | {"en", "ja"}):
            for k, text in made.items():
                langs.setdefault(lang, {}).setdefault(k, text)
        print("  %d keys borrowed from other mods, %d made up from the key"
              % (len(found), len(made)))
    if not langs:
        print("no strings.lua in this mod")
        return
    write(os.path.join(v.dst, "strings.json"),
          json.dumps(langs, indent="\t", ensure_ascii=False) + "\n")
    print("strings.json written")


def readable_key(key):
    """Author_Car_1043_name -> "Author Car 1043"."""
    k = re.sub(r"_(name|desc|description)$", "", key, flags=re.I)
    return k.replace("_", " ").strip() or key


def borrowed_strings(keys):
    """{lang: {key: text}} for `keys`, from other installed mods' strings.lua."""
    want, out = set(keys), {}
    if not os.path.isdir(WORKSHOP):
        return out
    for mod in sorted(os.listdir(WORKSHOP)):
        p = os.path.join(WORKSHOP, mod, "strings.lua")
        if not os.path.exists(p):
            continue
        txt = read(p)
        if not any(k in txt for k in want):
            continue
        for lang, entries in parse_strings_lua(p).items():
            for k in sorted(want & set(entries)):
                out.setdefault(lang, {}).setdefault(k, entries[k])
    return out


def parse_strings_lua(src):
    txt = read(src)
    langs = {}
    for lm in re.finditer(r'(?m)^\t([a-z_]{2,8}) = \{$', txt):
        start = lm.end()
        depth, i = 1, start
        while depth:
            i += 1
            if txt[i] == "{":
                depth += 1
            elif txt[i] == "}":
                depth -= 1
        # include the closing brace: the last entry's lookahead needs it
        body = txt[start:i + 1]
        entries = {}
        for em in re.finditer(
                # the trailing comma is optional: the last entry in a block
                # often has none
                r'\["([^"]+)"\]\s*=\s*((?:"(?:[^"\\]|\\.)*"|\s|\.\.|\blb\b)+?),?\s*(?=\[|\})',
                body, re.S):
            entries[em.group(1)] = lua_string_expr(em.group(2))
        langs[lm.group(1)] = entries
    return langs


def cmd_consists(v):
    """TF2's res/config/multiple_unit/<name>.lua becomes <name>.mu.lua beside
    the models, with the vehicle paths made relative and `filterTags` added.

    Names: consists in sub-folders can share a file name with others
    (multiple_unit/a.lua and multiple_unit/<livery>/a.lua). Flattened on
    the name alone, the second overwrote the first and one livery's
    consists pointed at the other's cars. As for models, the shallowest
    keeps the plain name and the rest get their folder in front
    (<livery>_a.mu.lua).

    Groups: `groupFileName` on a multiple unit groups consists in the
    purchase menu, shown as variants of each other (api/type.d.tl,
    MultipleUnit). TF2 authors pointed it at a head consist (.lua) or a
    head model (.mdl, often an empty placeholder that build drops), so the
    value is rewritten to a consist that exists in the group. Unlike a
    model's (a ResName, resolved against the file), a multiple unit's is a
    plain string compared with the head's resource name, so it is written
    in full: <modId>::/<contentDir>/<head>.mu - the resource name drops
    ".lua" (checked in game: multipleUnitRep.getName). The head carries none:
    the store window hides every multiple unit with a group, head or not
    (gui.zip, vehicle_store_window.tl). Mods without groups get one, by the
    same rules as vehicles in `menu` (menuGroup false turns it off)."""
    src_dir = os.path.join(v.res, "config", "multiple_unit")
    if not os.path.isdir(src_dir):
        print("no multiple unit configs in this mod")
        return
    rels = sorted(os.path.relpath(os.path.join(r, f), src_dir).replace(os.sep, "/")
                  for r, _, fs in os.walk(src_dir) for f in fs if f.endswith(".lua"))
    by_name = {}
    for rel in sorted(rels, key=lambda r: (r.count("/"), r)):
        stem = tf3_name(os.path.splitext(os.path.basename(rel))[0])
        if stem in by_name.values():
            parent = os.path.basename(os.path.dirname(rel))
            stem = tf3_name(parent) + "_" + stem
        by_name[rel] = stem

    # the TF2 group of each consist, as written (relative to multiple_unit/
    # for .lua, a model path for .mdl)
    texts, group = {}, {}
    for rel in rels:
        txt = read(os.path.join(src_dir, *rel.split("/")))
        texts[rel] = txt
        g = re.search(r'groupFileName\s*=\s*"([^"]*)"', txt)
        group[rel] = g.group(1).replace("\\", "/").lower() if g and g.group(1) else None

    # a group whose TF2 head is one of our vehicles joins that vehicle's
    # group: vehicles and multiple units share variant groups in the store
    # (that is how a display-only model fronts a set of consists). The
    # vehicle may itself be a member of another head after `menu`.
    vehicle_group = {}
    for g in sorted(set(x for x in group.values() if x and x.endswith(".mdl"))):
        ref = model_ref(v, g)
        p = os.path.join(v.veh, ref)
        if os.path.exists(p):
            h = re.search(r'groupFileName = "([^"]+\.mdl)",', read(p))
            head = h.group(1) if h else ref
            vehicle_group[g] = "%s::/%s/%s" % (v.mod_id, v.content_dir, head)

    # otherwise one head consist per TF2 group: the named consist if it is
    # one of ours, else the first member
    lower = {r.lower(): r for r in rels}
    head_of = {}
    for g in sorted(set(x for x in group.values() if x)):
        if g in vehicle_group:
            continue
        members = [r for r in rels if group[r] == g]
        head = lower.get(g) if g.endswith(".lua") else None
        if head is None:
            head = members[0]
        head_of[g] = head
    # a head belongs to its own group (TF2 heads often left the field empty)
    for g, head in head_of.items():
        if group[head] is None:
            group[head] = g
    loose = [r for r in rels if group[r] is None]
    if loose and v.cfg.get("menuGroup", True) is not False:
        if len(head_of) + len(vehicle_group) == 1:
            only = next(iter(head_of or vehicle_group))
            for r in loose:
                group[r] = only
        elif not head_of and not vehicle_group and len(rels) > 1:
            group.update({r: "<all>" for r in rels})
            head_of["<all>"] = rels[0]

    n = 0
    for rel in rels:
        stem = by_name[rel]
        txt = lift_strings(v, texts[rel], "mu_" + stem)
        txt = re.sub(r'name = "([^"]+\.mdl)"',
                     lambda m: 'name = "%s"' % model_ref(v, m.group(1)), txt)
        txt = re.sub(r'(?m)^\s*groupFileName = "[^"]*",?\n', "", txt)
        # any indentation: some authors use spaces, and a missed match left
        # the consist without filterTags - listed nowhere
        if "filterTags" not in txt:
            txt = re.sub(r'(?m)^([ \t]*return \{)[ \t]*$',
                         '\\1\n\t\tfilterTags = { "default" },', txt, count=1)
        g = group[rel]
        head = head_of.get(g) if g else None
        full = vehicle_group.get(g) if g else None
        if head and head != rel:
            full = "%s::/%s/%s.mu" % (v.mod_id, v.content_dir, by_name[head])
        if full:
            txt = re.sub(r'(?m)^([ \t]*return \{)[ \t]*$',
                         lambda m: '%s\n\t\tgroupFileName = "%s",' % (m.group(1), full),
                         txt, count=1)
        out = stem + ".mu.lua"
        write(os.path.join(v.veh, out), txt)
        label = ("HEAD" if head == rel else "group " + full.split("/")[-1]) if (head or full) else ""
        print("  %-44s -> %-28s %s" % (rel, out, label))
        n += 1
    print("%d consists in %d groups" % (n, len(set(head_of.values())) + len(set(vehicle_group.values()))))
    add_lifted_strings(v)


def add_lifted_strings(v):
    """Put the texts lift_strings took out of the consists into strings.json.

    `strings` runs before `consists`, so in a single `all` the consists'
    keys never reached strings.json: a consist named in Japanese showed as
    ◆<modId>_mu_<name>_1 in the menu. Ports that ran `post` twice hid it."""
    lifted = os.path.join(v.dst, "_metadata", BUILD_STRINGS)
    if not os.path.exists(lifted):
        return
    table = json.load(open(lifted, encoding="utf-8"))
    sj = os.path.join(v.dst, "strings.json")
    langs = json.load(open(sj, encoding="utf-8")) if os.path.exists(sj) else {}
    added = 0
    for lang in sorted(set(langs) | {"en", "ja"}):
        entries = langs.setdefault(lang, {})
        for k, text in table.items():
            if k not in entries:
                entries[k] = text
                added += 1
    if added:
        write(sj, json.dumps(langs, indent="\t", ensure_ascii=False) + "\n")
        print("  %d consist texts added to strings.json" % added)
