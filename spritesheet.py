#!/usr/bin/env python3
"""
spritesheet.py

A PNG sprite sheet builder using only the Python standard library. No installs or dependencies required.

Usage, run the command in the image directory:

python spritesheet.py

(python3 spritesheet.py on macOS)

This will result in spritesheet.png in the image directory)

Or to control the number of columns, amount of padding and output name:

python spritesheet.py --columns 8 --padding 2 --output sheet.png

(python3 spritesheet.py --columns 8 --padding 2 --output sheet.png)

Notes:

- Input images must be PNG.
- Supports common 8 bit PNG formats: RGBA, RGB, grayscale, grayscale + alpha, indexed/paletted PNG with optional transparency
- Interlaced PNGs are not supported.
- Images are packed into equal-size cells based on the largest input image, but it is better for all input images to share the same dimensions in the first place.

"""

import argparse
import math
import os
import struct
import sys
import zlib
from pathlib import Path


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def read_chunks(data):
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("Not a PNG file")

    pos = len(PNG_SIGNATURE)
    while pos < len(data):
        if pos + 8 > len(data):
            raise ValueError("Truncated PNG")

        length = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        start = pos + 8
        end = start + length

        if end + 4 > len(data):
            raise ValueError("Truncated PNG chunk")

        chunk_data = data[start:end]
        yield chunk_type, chunk_data
        pos = end + 4


def paeth(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)

    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def unfilter_scanlines(raw, width, height, bytes_per_pixel, stride):
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise ValueError(
            f"Unexpected decompressed data size: got {len(raw)}, expected {expected}"
        )

    rows = []
    pos = 0
    previous = bytearray(stride)

    for _ in range(height):
        filter_type = raw[pos]
        pos += 1
        scan = bytearray(raw[pos:pos + stride])
        pos += stride

        recon = bytearray(stride)

        for x in range(stride):
            left = recon[x - bytes_per_pixel] if x >= bytes_per_pixel else 0
            up = previous[x]
            up_left = previous[x - bytes_per_pixel] if x >= bytes_per_pixel else 0

            if filter_type == 0:
                value = scan[x]
            elif filter_type == 1:
                value = (scan[x] + left) & 0xFF
            elif filter_type == 2:
                value = (scan[x] + up) & 0xFF
            elif filter_type == 3:
                value = (scan[x] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                value = (scan[x] + paeth(left, up, up_left)) & 0xFF
            else:
                raise ValueError(f"Unsupported PNG filter type: {filter_type}")

            recon[x] = value

        rows.append(bytes(recon))
        previous = recon

    return rows


def unpack_samples(row, bit_depth, count):
    if bit_depth == 8:
        return list(row[:count])

    if bit_depth not in (1, 2, 4):
        raise ValueError(f"Unsupported bit depth: {bit_depth}")

    mask = (1 << bit_depth) - 1
    result = []

    for byte in row:
        bits_remaining = 8
        while bits_remaining >= bit_depth and len(result) < count:
            bits_remaining -= bit_depth
            result.append((byte >> bits_remaining) & mask)

    return result


def load_png(path):
    data = Path(path).read_bytes()

    width = height = None
    bit_depth = color_type = interlace = None
    palette = None
    transparency = None
    compressed = bytearray()

    for chunk_type, chunk_data in read_chunks(data):
        if chunk_type == b"IHDR":
            (
                width,
                height,
                bit_depth,
                color_type,
                compression,
                filter_method,
                interlace,
            ) = struct.unpack(">IIBBBBB", chunk_data)

            if compression != 0 or filter_method != 0:
                raise ValueError("Unsupported PNG compression/filter method")

            if interlace != 0:
                raise ValueError("Interlaced PNGs are not supported")

        elif chunk_type == b"PLTE":
            palette = [
                tuple(chunk_data[i:i + 3])
                for i in range(0, len(chunk_data), 3)
            ]

        elif chunk_type == b"tRNS":
            transparency = chunk_data

        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)

        elif chunk_type == b"IEND":
            break

    if width is None or height is None:
        raise ValueError("PNG is missing IHDR")

    channels_by_type = {
        0: 1,  # grayscale
        2: 3,  # RGB
        3: 1,  # indexed
        4: 2,  # grayscale + alpha
        6: 4,  # RGBA
    }

    if color_type not in channels_by_type:
        raise ValueError(f"Unsupported PNG color type: {color_type}")

    channels = channels_by_type[color_type]

    if color_type in (2, 4, 6) and bit_depth != 8:
        raise ValueError(
            f"Only 8-bit truecolor/alpha PNGs are supported; got {bit_depth}-bit"
        )

    if color_type == 0 and bit_depth not in (1, 2, 4, 8):
        raise ValueError(f"Unsupported grayscale bit depth: {bit_depth}")

    if color_type == 3 and bit_depth not in (1, 2, 4, 8):
        raise ValueError(f"Unsupported indexed PNG bit depth: {bit_depth}")

    bits_per_pixel = channels * bit_depth
    stride = (width * bits_per_pixel + 7) // 8
    bytes_per_pixel = max(1, (bits_per_pixel + 7) // 8)

    raw = zlib.decompress(bytes(compressed))
    rows = unfilter_scanlines(raw, width, height, bytes_per_pixel, stride)

    rgba = bytearray(width * height * 4)
    out = 0

    if color_type == 6:
        for row in rows:
            for x in range(width):
                i = x * 4
                rgba[out:out + 4] = row[i:i + 4]
                out += 4

    elif color_type == 2:
        transparent_rgb = None
        if transparency and len(transparency) >= 6:
            r16, g16, b16 = struct.unpack(">HHH", transparency[:6])
            transparent_rgb = (r16 & 0xFF, g16 & 0xFF, b16 & 0xFF)

        for row in rows:
            for x in range(width):
                i = x * 3
                rgb = (row[i], row[i + 1], row[i + 2])
                alpha = 0 if transparent_rgb == rgb else 255
                rgba[out:out + 4] = bytes((*rgb, alpha))
                out += 4

    elif color_type == 4:
        for row in rows:
            for x in range(width):
                i = x * 2
                gray = row[i]
                alpha = row[i + 1]
                rgba[out:out + 4] = bytes((gray, gray, gray, alpha))
                out += 4

    elif color_type == 0:
        transparent_gray = None
        if transparency and len(transparency) >= 2:
            transparent_gray = struct.unpack(">H", transparency[:2])[0]

        max_sample = (1 << bit_depth) - 1

        for row in rows:
            samples = unpack_samples(row, bit_depth, width)
            for sample in samples:
                gray = round(sample * 255 / max_sample)
                alpha = 0 if transparent_gray == sample else 255
                rgba[out:out + 4] = bytes((gray, gray, gray, alpha))
                out += 4

    elif color_type == 3:
        if palette is None:
            raise ValueError("Indexed PNG is missing PLTE palette")

        alpha_table = list(transparency or b"")

        for row in rows:
            indexes = unpack_samples(row, bit_depth, width)
            for index in indexes:
                if index >= len(palette):
                    raise ValueError("Palette index out of range")

                r, g, b = palette[index]
                a = alpha_table[index] if index < len(alpha_table) else 255
                rgba[out:out + 4] = bytes((r, g, b, a))
                out += 4

    return width, height, bytes(rgba)


def make_chunk(chunk_type, data):
    crc = zlib.crc32(chunk_type)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", crc)
    )


def save_rgba_png(path, width, height, rgba):
    expected = width * height * 4
    if len(rgba) != expected:
        raise ValueError(f"RGBA buffer has {len(rgba)} bytes; expected {expected}")

    raw = bytearray()
    stride = width * 4

    for y in range(height):
        raw.append(0)  # PNG filter type 0: None
        start = y * stride
        raw.extend(rgba[start:start + stride])

    ihdr = struct.pack(
        ">IIBBBBB",
        width,
        height,
        8,   # bit depth
        6,   # RGBA
        0,   # compression
        0,   # filter
        0,   # no interlace
    )

    png = bytearray(PNG_SIGNATURE)
    png.extend(make_chunk(b"IHDR", ihdr))
    png.extend(make_chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
    png.extend(make_chunk(b"IEND", b""))

    Path(path).write_bytes(png)


def blit(src, src_w, src_h, dst, dst_w, dst_h, dst_x, dst_y):
    for y in range(src_h):
        if dst_y + y < 0 or dst_y + y >= dst_h:
            continue

        src_start = y * src_w * 4
        src_end = src_start + src_w * 4
        dst_start = ((dst_y + y) * dst_w + dst_x) * 4

        if dst_start < 0 or dst_start + src_w * 4 > len(dst):
            raise ValueError("Internal blit bounds error")

        dst[dst_start:dst_start + src_w * 4] = src[src_start:src_end]


def natural_key(name):
    parts = []
    current = ""
    is_digit = None

    for ch in name.lower():
        ch_is_digit = ch.isdigit()

        if is_digit is None or ch_is_digit == is_digit:
            current += ch
            is_digit = ch_is_digit
        else:
            parts.append(int(current) if is_digit else current)
            current = ch
            is_digit = ch_is_digit

    if current:
        parts.append(int(current) if is_digit else current)

    return parts


def main():
    parser = argparse.ArgumentParser(
        description="Create a transparent PNG sprite sheet from PNG files."
    )
    parser.add_argument(
        "--columns",
        type=int,
        default=None,
        help="Number of columns. Defaults to a roughly square sheet.",
    )
    parser.add_argument(
        "--padding",
        type=int,
        default=0,
        help="Transparent padding around each cell in pixels. Default: 0",
    )
    parser.add_argument(
        "--output",
        default="spritesheet.png",
        help="Output filename. Default: spritesheet.png",
    )
    parser.add_argument(
        "--no-center",
        action="store_true",
        help="Place images at the top-left of each cell instead of centering them.",
    )
    args = parser.parse_args()

    if args.padding < 0:
        parser.error("--padding must be 0 or greater")

    if args.columns is not None and args.columns < 1:
        parser.error("--columns must be at least 1")

    cwd = Path.cwd()
    output_path = cwd / args.output

    png_files = [
        p for p in cwd.iterdir()
        if p.is_file()
        and p.suffix.lower() == ".png"
        and p.resolve() != output_path.resolve()
    ]

    png_files.sort(key=lambda p: natural_key(p.name))

    if not png_files:
        print("No PNG files found in the current directory.", file=sys.stderr)
        return 1

    images = []

    for path in png_files:
        try:
            w, h, pixels = load_png(path)
            images.append((path.name, w, h, pixels))
        except Exception as exc:
            print(f"Error reading {path.name}: {exc}", file=sys.stderr)
            return 1

    max_w = max(w for _, w, _, _ in images)
    max_h = max(h for _, _, h, _ in images)

    cell_w = max_w + args.padding * 2
    cell_h = max_h + args.padding * 2

    count = len(images)
    columns = args.columns or math.ceil(math.sqrt(count))
    rows = math.ceil(count / columns)

    sheet_w = columns * cell_w
    sheet_h = rows * cell_h
    sheet = bytearray(sheet_w * sheet_h * 4)  # initialized transparent

    for index, (name, w, h, pixels) in enumerate(images):
        col = index % columns
        row = index // columns

        base_x = col * cell_w + args.padding
        base_y = row * cell_h + args.padding

        if args.no_center:
            x = base_x
            y = base_y
        else:
            x = base_x + (max_w - w) // 2
            y = base_y + (max_h - h) // 2

        blit(pixels, w, h, sheet, sheet_w, sheet_h, x, y)

    save_rgba_png(output_path, sheet_w, sheet_h, sheet)

    print(
        f"Created {output_path.name}: "
        f"{sheet_w}x{sheet_h}px, "
        f"{count} sprites, "
        f"{columns} columns x {rows} rows, "
        f"cell {cell_w}x{cell_h}px"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
