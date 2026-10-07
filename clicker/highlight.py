"""Find solid highlighted buttons, such as the selected option of a TUI menu drawn only with color."""
from PIL import Image


def distance(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def background(image):
    # The most common color of a small copy is the terminal background.
    colors = image.resize((96, 48), Image.Resampling.NEAREST).getcolors(96 * 48)
    return max(colors)[1]


def find_highlights(image, min_width=40, max_width=420, min_height=10, max_height=70, contrast=60, tolerance=24):
    """Boxes (left, top, right, bottom) of filled rectangles that stand out from the background.

    A selected button is a solid block with padding on both sides of its label,
    so a long uniform run marks it and its edge columns give its full height.
    Text glyphs, thin borders and plain backgrounds do not qualify.
    """
    image = image.convert("RGB")
    width, height = image.size
    pixels = image.load()
    base = background(image)
    boxes = []

    def inside(x, y, color):
        return 0 <= y < height and distance(pixels[x, y], color) <= tolerance

    for y in range(0, height, 2):
        x = 0
        while x < width:
            color = pixels[x, y]
            if distance(color, base) <= contrast or any(left <= x < right and top <= y < bottom for left, top, right, bottom in boxes):
                x += 1
                continue
            start = x
            while x < width and distance(pixels[x, y], color) <= tolerance:
                x += 1
            if not min_width <= x - start <= max_width:
                continue
            left, right = start, x
            top = y
            while inside(left + 1, top - 1, color) and inside(right - 2, top - 1, color):
                top -= 1
            bottom = y + 1
            while inside(left + 1, bottom, color) and inside(right - 2, bottom, color):
                bottom += 1
            if min_height <= bottom - top <= max_height:
                boxes.append((left, top, right, bottom))
    return boxes
