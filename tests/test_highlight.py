from PIL import Image, ImageDraw
from clicker.highlight import find_highlights


def test_finds_filled_button_but_not_text_or_borders():
    image = Image.new("RGB", (500, 120), (12, 12, 12))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 50, 150, 70), fill=(250, 178, 60))      # selected button
    draw.text((55, 55), "Allow once", fill=(10, 10, 10))         # its label
    draw.rectangle((0, 0, 3, 119), fill=(250, 178, 60))          # thin border bar
    draw.text((200, 20), "$ rm -rf build", fill=(250, 178, 60))  # colored text
    draw.rectangle((180, 50, 300, 70), fill=(30, 30, 30))        # unselected button
    assert find_highlights(image) == [(40, 50, 151, 71)]


def test_plain_screen_has_no_highlights():
    assert find_highlights(Image.new("RGB", (300, 100), "black")) == []
