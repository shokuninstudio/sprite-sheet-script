# Sprite Sheet Script

A PNG sprite sheet builder using only the Python standard library. No installs or dependencies required.

# Usage

Run the command in the image directory:

python spritesheet.py

(or on macOS: python3 spritesheet.py)

This will result in spritesheet.png in the image directory.

Or to control the number of columns, amount of padding and output name:

python spritesheet.py --columns 8 --padding 2 --output sheet.png

(or on macOS: python3 spritesheet.py --columns 8 --padding 2 --output sheet.png)

# Notes:

- Input images must be PNG.
- Supports common 8 bit PNG formats: RGBA, RGB, grayscale, grayscale + alpha, indexed/paletted PNG with optional transparency
- Interlaced PNGs are not supported.
- Images are packed into equal-size cell
