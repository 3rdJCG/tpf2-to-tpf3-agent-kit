"""Steps that need the Model Editor; editor.py clicks its buttons."""

EDITOR_STEPS = ("convert", "resave", "validate", "genicons")


def run_editor(v, ops):
    from . import editor
    out = editor.run(v.mod_id, v.content_dir, ops)
    for op, text in out.items():
        found = editor.problems(text)
        print("%s: %d problem lines in the log" % (op, len(found)))
        for line in found[:20]:
            print("  " + line.split("]", 1)[-1].strip())
    print("(the editor also shows some warnings only on screen - texture "
          "formats are covered by `check`)")
