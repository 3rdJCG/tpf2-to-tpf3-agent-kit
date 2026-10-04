"""Read and write the data-only Lua files the game uses (.msh, .mtl).

`parse` reads `function data() return <table> end` where the table holds only
literals, plus calls written as `name(literal, ...)` - the `_("...")` that
marks a translatable string in a .mdl, `transf.scaleRotZTransl(...)` in an
.ani. Keyed tables come back as dicts (in
file order), positional ones as lists, calls as Call. Anything else (local
variables, arithmetic, `require`) raises LuaSyntaxError, so a file that needs
real Lua fails loudly rather than being half read.

`dump` writes a table the way the Model Editor saves it, so that converted
files compare byte for byte with the editor's:

    function data()
    return {
    		key = {
    			...
    		},
    	}
    end

keys sorted, a keyed table opens with "{ " and a list of tables with "{",
a list of scalars sits on one line as "{ 1, 0, }", an empty table is "{ }",
CRLF line ends, no newline after the closing `end`.
"""
import re


class LuaSyntaxError(ValueError):
    pass


class Call(object):
    """`name(args...)` kept as written, e.g. Call("_", ["Class 1 diesel"])."""

    def __init__(self, name, args):
        self.name, self.args = name, list(args)

    def __eq__(self, other):
        return isinstance(other, Call) and (self.name, self.args) == (other.name, other.args)

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(self.name)

    def __repr__(self):
        return "Call(%r, %r)" % (self.name, self.args)


_TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<comment>--\[(?P<eq>=*)\[.*?\](?P=eq)\]|--[^\n]*)
  | (?P<number>0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<longstring>\[(?P<leq>=*)\[.*?\](?P=leq)\])
  | (?P<string>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')
  | (?P<name>[A-Za-z_]\w*)
  | (?P<op>[{}\[\]=,;().-])
""", re.S | re.X)

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f",
            "v": "\v", "\\": "\\", '"': '"', "'": "'", "\n": "\n"}


def _tokens(text):
    pos, out = 0, []
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            line = text.count("\n", 0, pos) + 1
            raise LuaSyntaxError("line %d: unexpected %r" % (line, text[pos:pos + 20]))
        pos = m.end()
        kind = m.lastgroup
        if kind in ("space", "comment"):
            continue
        value = m.group(kind)
        if kind == "longstring":
            # [[...]] / [==[...]==]: no escapes, a newline right after the
            # opening bracket is not part of the string, and Lua reads any
            # line break inside as "\n"
            n = len(m.group("leq")) + 2
            value = re.sub(r"^\r?\n", "", value[n:-n]).replace("\r\n", "\n")
        out.append((kind, value, text.count("\n", 0, m.start()) + 1))
    out.append(("eof", "", text.count("\n") + 1))
    return out


def _unquote(s):
    body, out, i = s[1:-1], [], 0
    while i < len(body):
        c = body[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        e = body[i + 1]
        if e in _ESCAPES:
            out.append(_ESCAPES[e])
            i += 2
        elif e.isdigit():
            m = re.match(r"\d{1,3}", body[i + 1:])
            out.append(chr(int(m.group())))
            i += 1 + len(m.group())
        else:
            raise LuaSyntaxError("unsupported escape \\%s" % e)
    return "".join(out)


class _Parser(object):
    def __init__(self, text):
        self.toks = _tokens(text)
        self.i = 0

    def peek(self, k=0):
        return self.toks[self.i + k]

    def take(self, value=None):
        tok = self.toks[self.i]
        if value is not None and tok[1] != value:
            raise LuaSyntaxError("line %d: expected %r, got %r" % (tok[2], value, tok[1]))
        self.i += 1
        return tok

    def value(self):
        kind, text, line = self.peek()
        if text == "{":
            return self.table()
        if text == "-" and self.peek(1)[0] == "number":
            self.take()
            return -self.number(self.take()[1])
        if kind == "number":
            return self.number(self.take()[1])
        if kind == "string":
            return _unquote(self.take()[1])
        if kind == "longstring":
            return self.take()[1]
        if kind == "name" and text in ("true", "false", "nil"):
            self.take()
            return {"true": True, "false": False, "nil": None}[text]
        if kind == "name" and self.peek(1)[1] in ("(", "."):
            self.take()
            while self.peek()[1] == ".":
                self.take()
                tok = self.take()
                if tok[0] != "name":
                    raise LuaSyntaxError("line %d: expected a name after '.'" % tok[2])
                text += "." + tok[1]
            self.take("(")
            args = []
            while self.peek()[1] != ")":
                args.append(self.value())
                if self.peek()[1] == ",":
                    self.take()
            self.take(")")
            return Call(text, args)
        raise LuaSyntaxError("line %d: not a literal: %r" % (line, text))

    @staticmethod
    def number(text):
        if text[:2] in ("0x", "0X"):
            return int(text, 16)
        if re.match(r"^\d+$", text):
            return int(text)
        return float(text)

    def table(self):
        self.take("{")
        keyed, items = {}, []
        while self.peek()[1] != "}":
            kind, text, _ = self.peek()
            if kind == "name" and self.peek(1)[1] == "=":
                self.take()
                self.take("=")
                keyed[text] = self.value()
            elif text == "[":
                self.take()
                key = self.value()
                self.take("]")
                self.take("=")
                keyed[key] = self.value()
            else:
                items.append(self.value())
            if self.peek()[1] in (",", ";"):
                self.take()
            elif self.peek()[1] != "}":
                tok = self.peek()
                raise LuaSyntaxError("line %d: expected ',' or '}', got %r" % (tok[2], tok[1]))
        self.take("}")
        if keyed and items:
            for n, item in enumerate(items, 1):
                keyed[n] = item
            return keyed
        return keyed if keyed or not items else items


def parse(text):
    """The table returned by `function data() return {...} end`."""
    p = _Parser(text.lstrip("\ufeff"))
    for word in ("function", "data", "(", ")", "return"):
        p.take(word)
    value = p.value()
    p.take("end")
    if p.peek()[0] != "eof":
        raise LuaSyntaxError("line %d: trailing %r" % (p.peek()[2], p.peek()[1]))
    return value


NL = "\r\n"


def _key(k):
    if isinstance(k, str) and re.match(r"^[A-Za-z_]\w*$", k):
        return k
    return "[%s]" % _scalar(k)


def _scalar(v, float_fmt=repr):
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "nil"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return float_fmt(v)
    if isinstance(v, str):
        if "\n" in v and "]]" not in v:
            # the editor writes text with line breaks as a long string
            return "[[" + v.replace("\n", NL) + "]]"
        return '"%s"' % v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    raise TypeError("cannot write %r as Lua" % (v,))


def g6(x):
    """A float as the editor writes it in .mtl files: C's %g, 6 significant
    digits (0.533999979 -> 0.534, 20000.0 -> 20000)."""
    return "%g" % x


def _sort_key(k):
    return (0, k, "") if isinstance(k, (int, float)) else (1, 0, str(k))


def _is_scalar(v):
    return not isinstance(v, (dict, list, Call))


def _dump(v, depth, out, ff):
    pad = "	" * (depth + 1)
    if isinstance(v, (dict, list)) and not v:
        out.append("{ }")
    elif isinstance(v, dict):
        out.append("{ " + NL)
        for k in sorted(v, key=_sort_key):
            out.append(pad + _key(k) + " = ")
            _dump(v[k], depth + 1, out, ff)
            out.append("," + NL)
        out.append("	" * depth + "}")
    elif isinstance(v, list) and all(_is_scalar(x) for x in v):
        # a vector or a list of numbers: one line, "{ 1, 0, }"
        out.append("{ " + "".join(_scalar(x, ff) + ", " for x in v) + "}")
    elif isinstance(v, list):
        out.append("{" + NL)
        for item in v:
            out.append(pad)
            _dump(item, depth + 1, out, ff)
            out.append("," + NL)
        out.append("	" * depth + "}")
    elif isinstance(v, Call):
        out.append(v.name + "(")
        for n, arg in enumerate(v.args):
            out.append(", " if n else "")
            _dump(arg, depth, out, ff)
        out.append(")")
    else:
        out.append(_scalar(v, ff))


def dump(value, float_fmt=repr):
    """`value` as a data file in the Model Editor's layout (a str with CRLFs).
    float_fmt writes a float; the editor's .mtl use g6."""
    out = ["function data()" + NL + "return "]
    _dump(value, 1, out, float_fmt)
    out.append(NL + "end")
    return "".join(out)
