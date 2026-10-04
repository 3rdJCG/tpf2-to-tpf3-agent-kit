"""menu: put the vehicles back in the purchase menu."""
import collections
import json
import os
import re
import sys

from .build import base_files, model_ref
from .common import read, write


def cmd_menu(v):
    """Put the vehicles back in the purchase menu.

    `filterTags` is what the menu filters on. The conversion leaves it empty
    for anything TF2 marked `multipleUnitOnly` - but TF3 has no such flag, so
    the cars end up listed nowhere at all. Compare a locomotive, which comes
    out with `{ "default" }`.

    Also fixes .mdl-to-.mdl references: `groupFileName` groups variants under
    one menu entry and still points at the TF2 path after conversion.
    """
    tagged = refs = 0
    for model in v.models():
        p = os.path.join(v.veh, model + ".mdl")
        txt = read(p)
        before = txt
        if DISPLAY_ONLY.search(model):
            # a display-only consist model (the picture for a group) must
            # not be for sale. Empty filterTags on a group head makes the
            # store show it as the group only (variantGroupOnly in
            # vehicle_store_window.tl); on a member, it keeps it unlisted.
            txt = re.sub(r'(?m)^(\t+)filterTags = \{[^\n]*\},$',
                         '\\1filterTags = { },', txt)
        else:
            txt = re.sub(r'(?m)^(\t+)filterTags = \{ \},$',
                         '\\1filterTags = { "default", },', txt)
        # bare file names too: one mod writes groupFileName =
        # "AuthorEmuCarA.mdl", and an uppercase reference to a model
        # that exists in lowercase kills the game while it loads (an
        # assertion in resource::Fixer::Model) - found by port.py smoke
        txt = re.sub(r'groupFileName = "([^"]+\.mdl)"',
                     lambda m: 'groupFileName = "%s"' % model_ref(v, m.group(1)),
                     txt)
        if txt != before:
            write(p, txt)
            if 'filterTags = { },' in before:
                tagged += 1
            if re.search(r'groupFileName = "[^"]*/', before):
                refs += 1

    # crewModels name TF2 base characters as characters/<x>.mdl; TF3 keeps
    # them one folder deeper, ::/characters/<x>/<x>.mdl
    for model in v.models():
        p = os.path.join(v.veh, model + ".mdl")
        txt = read(p)

        def crew(m):
            stem = os.path.splitext(os.path.basename(m.group(1)))[0]
            for cand in ("::/%s" % m.group(1),
                         "::/characters/%s/%s.mdl" % (stem, stem)):
                if cand in base_files():
                    return '"%s"' % cand
            return m.group(0)

        new = re.sub(r'(?<=crewModels = \{ )"(characters/[^"]+\.mdl)"', crew, txt)
        if new != txt:
            write(p, new)
            print("  %s.mdl: crew model -> base" % model)

    # some EMU mods give their cars name = "" (TF2 sold them as consists only);
    # TF3 lists them, blank. Name them after the mod and the model.
    title = re.sub(r"\s*\(TF2 port WIP\)$", "", v.cfg.get("modName", v.name))
    title = re.sub(r"\s*～.*$", "", title).strip()
    named = 0
    for model in v.models():
        p = os.path.join(v.veh, model + ".mdl")
        txt = read(p)
        label = "%s %s" % (title, re.sub(r"_ver\d+$", "", model))
        new = re.sub(r'(description = \{\s*\n\s*name = )"",',
                     lambda m: '%s"%s",' % (m.group(1), label), txt, count=1)
        if "description = {" not in new:
            # one EMU's cars have no description at all
            new = re.sub(r'(?m)^(\t+)(availability = \{)',
                         lambda m: '%sdescription = {\n%s\tname = "%s",\n%s},\n%s%s'
                         % (m.group(1), m.group(1), label, m.group(1),
                            m.group(1), m.group(2)), new, count=1)
        if new != txt:
            write(p, new)
            named += 1
    if named:
        print("  %d cars had no name -> \"%s <model>\"" % (named, title))

    # build drops empty placeholder models, and those were often the group
    # head (an empty display model): the game then logs "referenced
    # model not found" per car. Let the first real member head the group.
    members = collections.defaultdict(list)
    for model in v.models():
        m = re.search(r'groupFileName = "([^"]+)\.mdl"',
                      read(os.path.join(v.veh, model + ".mdl")))
        if m and not os.path.exists(os.path.join(v.veh, m.group(1) + ".mdl")):
            members[m.group(1)].append(model)
    for gone, models in sorted(members.items()):
        head = sorted(models)[0]
        for model in models:
            p = os.path.join(v.veh, model + ".mdl")
            write(p, read(p).replace('groupFileName = "%s.mdl"' % gone,
                                     'groupFileName = "%s.mdl"' % head))
        print("  group head %s.mdl is gone -> %s.mdl (%d cars)" % (gone, head, len(models)))
    print("filterTags filled: %d, groupFileName retargeted: %d" % (tagged, refs))
    group_menu(v)


GROUP_RE = re.compile(r'groupFileName = "([^"]+)\.mdl",')
# display-only consist models (<name>_menu, <name>_group) must not
# head a group: they are sold as vehicles of their own (roadmap, unresolved 6)
DISPLAY_ONLY = re.compile(r"_(menu|group)$")


def group_menu(v):
    """Group a mod's vehicles under one entry in the purchase menu.

    `groupFileName = "<head>.mdl"` in transportVehicle puts a model under that
    head's entry. The head itself must NOT carry it: the store window
    (gui.zip, vehicle_store_window.tl) lists the head and then every model
    whose group is the head's path, so a head naming itself shows twice.
    TF2 authors usually wrote it on the head too; it is removed. Mods whose authors set it - a
    locomotive's seven variants, a family of coaches - show as one entry with a list; the rest
    list every car separately. By default every car of a mod goes under one
    head, chosen as the face of the entry: a car with a driver's seat
    (`crew = true`) and an engine, else one with a driver's seat, else one
    with an engine, else any - so an EMU is shown by its cab car, not by an
    intermediate motor car. Display-only consist models never head a group.

    Authors' own groups are kept. With one existing group, ungrouped cars
    join it; with several, nothing is changed. The cars grouped here are
    recorded in _metadata/menu_groups.json, so a re-run chooses again
    instead of taking its own earlier choice for the author's. Config:
        "menuGroup": false                          leave the mod as it is
        "menuHead": "<model>"                       this head instead of the chosen one
        "menuGroups": {"<head>": ["<model>", ...]}  exactly these groups
    """
    if v.cfg.get("menuGroup", True) is False:
        print("menu groups: off in the config")
        return
    models = v.models()
    if len(models) < 2:
        print("menu groups: one model, nothing to group")
        return
    stamp = os.path.join(v.dst, "_metadata", "menu_groups.json")
    ours = set(json.load(open(stamp, encoding="utf-8"))) if os.path.exists(stamp) else set()
    text = {m: read(os.path.join(v.veh, m + ".mdl")) for m in models}
    current = {}
    for m in models:
        g = GROUP_RE.search(text[m])
        current[m] = g.group(1) if g else None
    author = {m: h for m, h in current.items() if h and m not in ours}

    explicit = v.cfg.get("menuGroups")
    if explicit:
        want = {}
        for head, members in explicit.items():
            for m in [head] + list(members):
                if m not in text:
                    sys.exit("menuGroups: no model %s.mdl in %s" % (m, v.veh))
                want[m] = head
    else:
        heads = set(author.values())
        loose = [m for m in models if m not in author]
        # an author's head that named itself is not loose: it heads a group
        loose = [m for m in loose if m not in heads]
        if not loose:
            head = None
            print("menu groups: the author grouped all %d models" % len(models))
        elif len(heads) > 1:
            head = None
            print("menu groups: the author made %d groups - left alone, %d "
                  "cars ungrouped (set menuGroups to change)" % (len(heads), len(loose)))
        elif heads:
            head = heads.pop()
        elif v.cfg.get("menuHead"):
            # for mods that mark neither driver's seats nor engines the usual way
            head = v.cfg["menuHead"]
            if head not in text:
                sys.exit("menuHead: no model %s.mdl in %s" % (head, v.veh))
        else:
            cands = [m for m in models if not DISPLAY_ONLY.search(m)] or models

            def rank(m):
                cab = "crew = true" in text[m]
                powered = bool(re.search(r"engines = \{\s*\{", text[m]))
                return (not (cab and powered), not cab, not powered, m)
            head = min(cands, key=rank)
        want = {m: head for m in loose} if head else {}

    changed = 0
    for m, head in sorted(want.items()):
        if current[m] == head or m == head:
            continue
        line = 'groupFileName = "%s.mdl",' % head
        if current[m] is not None:
            new = GROUP_RE.sub(line, text[m], count=1)
        else:
            # keys are written in alphabetical order; groupFileName follows filterTags
            new, n = re.subn(r'(?m)^(\t+)(filterTags = \{[^\n]*\},)$',
                             lambda g: "%s%s\n%s%s" % (g.group(1), g.group(2),
                                                       g.group(1), line),
                             text[m], count=1)
            if not n:
                print("  %s.mdl: no filterTags line - not grouped" % m)
                continue
        write(os.path.join(v.veh, m + ".mdl"), new)
        changed += 1
    # heads, ours and the authors': drop the self-reference
    unheaded = 0
    for m in models:
        p = os.path.join(v.veh, m + ".mdl")
        txt = read(p)
        g = GROUP_RE.search(txt)
        if g and g.group(1) == m:
            write(p, re.sub(r'(?m)^\t+groupFileName = "[^"]+\.mdl",\n', "", txt, count=1))
            unheaded += 1
    if want:
        write(stamp, json.dumps(sorted(m for m in want if m not in author), indent=4) + "\n")
        heads = sorted(set(want.values()))
        print("menu groups: %d of %d models under %s (%d changed)" % (
            len(want), len(models), ", ".join(h + ".mdl" for h in heads), changed))
    if unheaded:
        print("menu groups: %d head(s) no longer name themselves" % unheaded)
