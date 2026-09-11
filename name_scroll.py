"""Render names into strictly clipped bitmap windows on either matrix backend."""

from PIL import BdfFontFile, Image

class NameRenderer:
    HEIGHT = 6
    BASELINE = 5
    GAP = 8
    def __init__(self, font_path):
        # Read all BDF glyphs, including Unicode, without needing emulator code
        # on the Raspberry Pi. Pillow is already a production dependency.
        self.glyphs = {}
        self.cache = {}
        with open(font_path, "rb") as source:
            while True:
                glyph = BdfFontFile.bdf_char(source)
                if glyph is None:
                    break
                _, codepoint, metrics, bitmap = glyph
                self.glyphs[codepoint] = metrics, bitmap

    def bitmap(self, name):
        name = name or ""
        if name not in self.cache:
            fallback = self.glyphs[ord("?")]
            glyphs = [self.glyphs.get(ord(char), fallback) for char in name]
            width = sum(metrics[0][0] for metrics, _ in glyphs)
            image = Image.new("RGB", (max(1, width), self.HEIGHT))
            cursor = 0
            for (advance, bounds, source), glyph in glyphs:
                mask = glyph.crop(source)
                x, y = cursor + bounds[0], self.BASELINE + bounds[1]
                image.paste((255, 255, 255),
                            (x, y, x + mask.width, y + mask.height), mask)
                cursor += advance[0]
            self.cache[name] = image
        return self.cache[name]

    def text_width(self, name):
        return self.bitmap(name).width

    def fit_team_name(self, name, width):
        """Return the full name when it fits, otherwise a glyph-safe ellipsis."""
        name = name or ""
        if self.text_width(name) <= width:
            return name

        ellipsis = "..."
        ellipsis_width = 5  # Three one-pixel dots separated by one blank pixel.
        if ellipsis_width > width:
            return ""
        visible = ""
        used = 0
        budget = width - ellipsis_width
        for char in name:
            metrics, _ = self.glyphs.get(ord(char), self.glyphs[ord("?")])
            advance = metrics[0][0]
            if used + advance > budget:
                break
            visible += char
            used += advance
        return visible.rstrip() + ellipsis

    def team_window(self, name, width, right_align=False):
        """Render a full or compact-ellipsis-truncated name without scrolling."""
        name = name or ""
        if self.text_width(name) <= width:
            return self.window(name, width, right_align=right_align)

        display_name = self.fit_team_name(name, width)
        prefix = display_name[:-3]
        prefix_width = self.text_width(prefix) if prefix else 0
        rendered = Image.new("RGB", (prefix_width + 5, self.HEIGHT))
        if prefix:
            rendered.paste(self.bitmap(prefix), (0, 0))
        for dot_x in (0, 2, 4):
            rendered.putpixel((prefix_width + dot_x, 4), (255, 255, 255))

        tile = Image.new("RGB", (width, self.HEIGHT))
        x = width - rendered.width if right_align else 0
        tile.paste(rendered, (x, 0))
        return tile

    def static_window(self, name, width, right_align=False):
        """Truncate at whole-glyph boundaries; the classic layout never scrolls."""
        name = name or ""
        visible = ""
        used = 0
        for char in name:
            metrics, _ = self.glyphs.get(ord(char), self.glyphs[ord("?")])
            advance = metrics[0][0]
            if used + advance > width:
                break
            visible += char
            used += advance
        return self.window(visible, width, right_align=right_align)

    def window(self, name, width, offset=0, right_align=False):
        """Short names stay still; long names wrap with a small blank gap.

        PIL clips both copies to this tile before anything reaches the canvas.
        No name can draw outside its assigned rectangle.
        """
        tile = Image.new("RGB", (width, self.HEIGHT))
        text = self.bitmap(name)
        if text.width <= width:
            tile.paste(text, (width - text.width if right_align else 0, 0))
        else:
            period = text.width + self.GAP
            phase = int(offset) % period
            tile.paste(text, (-phase, 0))
            tile.paste(text, (period - phase, 0))
        return tile

    def bounce_window(self, name, width, offset=0, right_align=False):
        """Keep a long name visible while it travels between both clipped edges."""
        tile = Image.new("RGB", (width, self.HEIGHT))
        text = self.bitmap(name)
        if text.width <= width:
            tile.paste(text, (width - text.width if right_align else 0, 0))
            return tile

        overflow = text.width - width
        period = overflow * 2
        phase = int(offset) % period
        travel = phase if phase <= overflow else period - phase
        x = -overflow + travel if right_align else -travel
        tile.paste(text, (x, 0))
        return tile
