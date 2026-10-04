"""sounds: sound sets and 48 kHz audio."""
import audioop
import os
import re
import shutil
import wave

from .common import read, tf3_name, write


# TF2 wrote shared sounds as vehicle/<rest>; TF3 keeps the same tree under the
# train's shared folder.
SHARED_SOUND = "::/vehicle/train/shared/sound/%s"

# Stand-ins for sound sets in TF2's old soundeffectsutil format, by engine
# type. Japanese DMUs are hydraulic; "soundSetFallback" in the vehicle config
# overrides. None covers unpowered cars.
BASE_SOUND_SETS = {
    "DIESEL": "::/vehicle/train/shared/sound/train_diesel_hydraulic.snd",
    "ELECTRIC": "::/vehicle/train/shared/sound/train_electric_medium.snd",
    "STEAM": "::/vehicle/train/shared/sound/train_steam_old.snd",
    None: "::/vehicle/train/shared/sound/train_electric_medium.snd",
}

SAMPLE_RATE = 48000


def to_48k(src, dst):
    """TF3 validation rejects anything but 48 kHz; TF2 mods are full of 44.1."""
    with wave.open(src, "rb") as w:
        params = w.getparams()
        frames = w.readframes(params.nframes)
    if params.framerate == SAMPLE_RATE:
        shutil.copy2(src, dst)
        return False
    frames, _ = audioop.ratecv(frames, params.sampwidth, params.nchannels,
                               params.framerate, SAMPLE_RATE, None)
    with wave.open(dst, "wb") as w:
        w.setnchannels(params.nchannels)
        w.setsampwidth(params.sampwidth)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(frames)
    return True


def cmd_sounds(v):
    """Port a mod's own sound set.

    TF2 kept these in res/config/sound_set/<name>.lua and the model referenced
    them by bare name. TF3 wants <name>.snd.lua beside the model, referenced as
    a path ending .snd, and soundsetutil changed in two ways:

      addTrackParam01's last argument is {scriptingInfoKey, paramName} instead
      of a plain parameter name.

      addEventClacks' axleRefWeight is a weight, and weights went from tonnes
      to kilograms with the rest of the metadata - so it scales by 1000.
    """
    src_dir = os.path.join(v.res, "config", "sound_set")
    if not os.path.isdir(src_dir):
        print("no sound sets in this mod")
        return
    dst_dir = os.path.join(v.veh, "sound")
    os.makedirs(dst_dir, exist_ok=True)

    audio_root = os.path.join(v.res, "audio", "effects")
    own = {}
    for root, _, files in os.walk(audio_root):
        for fn in files:
            # only the audio: one EMU mod ships an idle.sfk (an audio
            # editor's waveform cache) beside its .wav files
            if not fn.lower().endswith(".wav"):
                continue
            rel = os.path.relpath(os.path.join(root, fn), audio_root)
            own[rel.replace(os.sep, "/").lower()] = os.path.join(root, fn)
    resampled = 0
    for rel, path in own.items():
        dst = os.path.join(dst_dir, *[tf3_name(p) for p in rel.split("/")])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if to_48k(path, dst):
            resampled += 1

    # "soundReplace" in the vehicle config: TF2 reference -> TF3 reference, for
    # sounds the original points at but never shipped (one locomotive's horn is
    # a whistle .wav which is in no installed mod nor in base)
    replace = {k.lower(): r for k, r in v.cfg.get("soundReplace", {}).items()}

    def wav(m):
        ref = m.group(1)
        if ref.lower() in replace:
            print("  replaced %s -> %s" % (ref, replace[ref.lower()]))
            return '"%s"' % replace[ref.lower()]
        if ref.lower() in own:
            return '"%s"' % "/".join(tf3_name(p) for p in ref.split("/"))
        rest = ref.split("/", 1)[1] if ref.startswith("vehicle/") else ref
        return '"%s"' % (SHARED_SOUND % rest)

    # Sets can sit in sub-folders (sound_set/<set>/<set>.lua) and
    # are still referenced by file name alone (name = "<set>").
    sets = sorted((fn, os.path.join(r, fn)) for r, _, fs in os.walk(src_dir)
                  for fn in fs if fn.endswith(".lua"))
    names = []
    for fn, src in sets:
        txt = read(src)
        if "soundeffectsutil" in txt:
            # TF2's older sound-set format: data() returns raw tracks whose
            # update functions call soundeffectsutil, which TF3 does not
            # have. Nothing to translate it into, so the models get one of
            # base's generic sets instead (see BASE_SOUND_SETS).
            names.append((os.path.splitext(fn)[0], None))
            print("  %-22s -> base set (old soundeffectsutil format)" % fn)
            continue
        # base's own .snd.lua writes "/scripts/..." because it is base; from a
        # mod that resolves inside the mod and the require fails. audioutil
        # too: a set that still says require "audioutil" fails to load and
        # the game reports the whole set "not found" (seen on several mods).
        txt = txt.replace('require "soundsetutil"',
                          'require "::/scripts/soundsetutil.lua"')
        txt = txt.replace('require "audioutil"',
                          'require "::/scripts/audioutil.lua"')
        txt = re.sub(r'"([^"]+\.wav)"', wav, txt)
        txt = re.sub(r'(addTrackParam01\((?:[^()]|\([^()]*\))*?,\s*)"([a-z0-9_]+)"\)',
                     lambda m: '%s{"vehicle", "%s"})' % (m.group(1), m.group(2)),
                     txt, flags=re.S)
        txt = re.sub(r'(addEventClacks\([^)]*?,\s*)([0-9.]+)\s*\)',
                     lambda m: "%s%s * 1000.0)" % (m.group(1), m.group(2)), txt)
        out = tf3_name(os.path.splitext(fn)[0]) + ".snd.lua"
        write(os.path.join(dst_dir, out), txt)
        names.append((os.path.splitext(fn)[0], "sound/" + out[:-4]))
        print("  %-22s -> sound/%s" % (fn, out))

    # the model referenced the set by bare name; TF3 wants a path
    for model in v.models():
        p = os.path.join(v.veh, model + ".mdl")
        txt = read(p)
        before = txt
        engine = re.search(r'type = "(DIESEL|ELECTRIC|STEAM)"', txt)
        fallback = v.cfg.get("soundSetFallback") or BASE_SOUND_SETS.get(
            engine.group(1) if engine else None, BASE_SOUND_SETS[None])
        for old, new in names:
            txt = txt.replace('name = "%s",' % old,
                              'name = "%s",' % (new or fallback))
            if new is None:
                # a model a previous run pointed at the unloadable copy
                txt = txt.replace('name = "sound/%s.snd",' % tf3_name(old),
                                  'name = "%s",' % fallback)
                stale = os.path.join(dst_dir, tf3_name(old) + ".snd.lua")
                if os.path.exists(stale):
                    os.remove(stale)
        if txt != before:
            write(p, txt)
            print("  %s.mdl -> sound set path" % model)
    print("%d wav copied (%d resampled to 48 kHz), %d sound sets (%d replaced by base)" % (
        len(own), resampled, len(names), sum(1 for _, n in names if n is None)))
