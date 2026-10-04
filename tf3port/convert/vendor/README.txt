Third-party code used by tf3port.convert.

tl.lua    Teal compiler v0.24.8, https://github.com/teal-language/tl (MIT, LICENSE-tl.txt).
          TF3 writes some of its base scripts in Teal (/scripts/mat4.tl, vec3.tl);
          the model conversion runs them, so they are compiled to Lua first.
