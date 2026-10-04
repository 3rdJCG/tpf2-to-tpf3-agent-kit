"""Reading and writing DDS files without a DDS library."""
import io
import struct

from PIL import Image


HEADER_LEN = 128

DX10_LEN = 20

DDSD_MIPMAPCOUNT = 0x20000

DDSCAPS_COMPLEX = 0x8

DDSCAPS_MIPMAP = 0x400000

BLOCK_BYTES = {"DXT1": 8, "DXT5": 16, "BC5U": 16, "DXT3": 16}


def fix_dds_header(header, w, h, fourcc):
    """Repair the fields Pillow leaves wrong for a block-compressed DDS.

    Taking the header from Pillow's DX10 output and only swapping the fourCC
    leaves `dwPitchOrLinearSize`, `dwDepth` and `dwRGBBitCount` describing
    something else. TF3 then reports the texture as missing, which is a
    confusing way to say "I could not parse this". Compare any base texture:
    linear size is the compressed byte count, depth is 1, bit count is 0."""
    block = BLOCK_BYTES.get(fourcc)
    if not block:
        return header
    header = bytearray(header)
    blocks = ((w + 3) // 4) * ((h + 3) // 4)
    struct.pack_into("<I", header, 20, blocks * block)   # dwPitchOrLinearSize
    struct.pack_into("<I", header, 24, 1)                # dwDepth
    struct.pack_into("<I", header, 88, 0)                # dwRGBBitCount
    return bytes(header)


def dds_with_mips(levels, encode_level):
    """Pillow writes one level per file; concatenate the block streams under a
    single header that advertises the whole chain."""
    header, first = encode_level(levels[0])
    header = bytearray(header)
    flags = struct.unpack_from("<I", header, 8)[0] | DDSD_MIPMAPCOUNT
    struct.pack_into("<I", header, 8, flags)
    struct.pack_into("<I", header, 28, len(levels))
    caps = struct.unpack_from("<I", header, 108)[0] | DDSCAPS_COMPLEX | DDSCAPS_MIPMAP
    struct.pack_into("<I", header, 108, caps)
    header = fix_dds_header(header, levels[0].size[0], levels[0].size[1],
                            bytes(header[84:88]).decode("latin1"))
    out = bytes(header) + first
    for lvl in levels[1:]:
        out += encode_level(lvl)[1]
    return out


def write_flat_normal(path):
    size = 64
    im = Image.new("RGB", (size, size), (128, 128, 255))
    levels, w = [im], size
    while w > 1:
        w //= 2
        levels.append(im.resize((w, w), Image.NEAREST))

    def encode_level(level):
        buf = io.BytesIO()
        level.save(buf, format="DDS", pixel_format="BC5")
        raw = buf.getvalue()
        # Pillow emits BC5 under a DX10 header; the base game uses legacy BC5U
        head = bytearray(raw[:HEADER_LEN])
        head[84:88] = b"BC5U"
        return head, raw[HEADER_LEN + DX10_LEN:]

    open(path, "wb").write(dds_with_mips(levels, encode_level))
    return len(levels)


def pot(n):
    lo = 1 << (n.bit_length() - 1)
    hi = lo << 1
    return lo if n - lo < hi - n else hi
