"""A code-authored 8-bit runner GIF and a 64x32 touchdown celebration renderer."""

from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageSequence

ASSET = Path(__file__).resolve().parent / "assets" / "touchdown_runner.gif"


# Six readable poses, held for two 50ms frames each: split, contact, passing,
# then the opposite leg leads. A compact stride and larger cleats keep the
# motion readable. The stride is rear-biased around the hip at x=6,
# with a restrained forward reach and a more pronounced backward push.
# Each leg is (knee, foot); rear leg is drawn first for clear depth.
SHOE_WIDTH = 4
SHOE_HEIGHT = 2
RUN_POSES = (
    (((8, 11), (8, 14)), ((3, 11), (1, 13)), 0),
    (((7, 12), (6, 15)), ((3, 11), (1, 12)), 1),
    (((6, 13), (4, 15)), ((7, 10), (5, 12)), 1),
    (((3, 11), (1, 13)), ((8, 11), (8, 14)), 0),
    (((3, 11), (1, 12)), ((7, 12), (6, 15)), 1),
    (((7, 10), (5, 12)), ((6, 13), (4, 15)), 1),
)


def runner_x(tick):
    return round(-16 + 80 * tick / 99)


def runner_foot(tick, phase_offset=0):
    """Foot location in the authored six-pose running cycle."""
    near, _, _ = RUN_POSES[((tick + phase_offset) // 2) % len(RUN_POSES)]
    return near[1]


def runner_sprite(tick):
    """Original football-player art with compact strides and visible cleats."""
    near, far, bob = RUN_POSES[(tick // 2) % len(RUN_POSES)]
    sprite = Image.new("RGBA", (16, 16))
    draw = ImageDraw.Draw(sprite)
    for (knee, foot), skin, shoe in ((far, "#a86645", "#a7b9cf"),
                                    (near, "#d99963", "#f5f5ee")):
        hip = (6, 9 + bob)
        draw.line((*hip, *knee, foot[0], foot[1] - SHOE_HEIGHT), fill=skin, width=2)
        # Thigh follows the raised knee, rather than stretching a straight shin.
        draw.line((*hip, *knee), fill=shoe, width=2)
        draw.rectangle((foot[0], foot[1] - SHOE_HEIGHT + 1,
                        foot[0] + SHOE_WIDTH - 1, foot[1]), fill=shoe)

    # One-pixel bounce on contact; the forward lean and tucked ball stay stable.
    body = Image.new("RGBA", (16, 11))
    torso = ImageDraw.Draw(body)
    torso.rectangle((5, 0, 10, 3), fill="#f5f5ee")
    torso.rectangle((5, 1, 6, 3), fill="#2879df")
    torso.rectangle((9, 3, 11, 4), fill="#d99963")
    torso.point((10, 3), fill="#172033")
    torso.line((11, 2, 12, 4), fill="#b4c5d5")
    torso.rectangle((4, 4, 9, 7), fill="#2879df")
    torso.line((7, 5, 7, 6), fill="white")
    # Free arm counter-swings; ball-carrying arm never releases the football.
    arm_poses = ((1, 6), (2, 8), (4, 8), (3, 8), (1, 7), (1, 5))
    arm_x, arm_y = arm_poses[(tick // 2) % len(RUN_POSES)]
    torso.line((4, 5, arm_x, arm_y), fill="#d99963", width=2)
    torso.rectangle((8, 6, 11, 7), fill="#d99963")
    torso.ellipse((10, 4, 14, 7), fill="#914d28")
    torso.line((11, 5, 13, 5), fill="#fff0cb")
    torso.rectangle((4, 8, 8, 9), fill="#f5f5ee")
    sprite.alpha_composite(body, (0, bob))
    return sprite


def runner_frames():
    """100 frames at 20fps: six-pose runner traverses a 64x16 field."""
    frames = []
    for tick in range(100):
        frame = Image.new("RGB", (64, 16), "#092717")
        turf = ImageDraw.Draw(frame)
        turf.line((0, 15, 63, 15), fill="#36a255")
        for x in range(4, 64, 16):
            turf.line((x, 15, x, 14), fill="#a0cd9f")
        sprite = runner_sprite(tick)
        frame.paste(sprite, (runner_x(tick), 0), sprite)
        frames.append(frame)
    return frames


def export_runner_gif(path=ASSET):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = runner_frames()
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=50, loop=0, disposal=2, optimize=False)


class CelebrationRenderer:
    def __init__(self, names, asset=ASSET):
        self.names = names
        with Image.open(asset) as gif:
            self.frames = [frame.convert("RGB").copy() for frame in ImageSequence.Iterator(gif)]
        self.reverse_frames = [frame.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                               for frame in self.frames]

    def _runner_field(self, touchdown, frame_index, reverse):
        """Reveal the owning fantasy team behind the moving runner."""
        field = (self.reverse_frames if reverse else self.frames)[frame_index].copy()
        if not touchdown.fantasy_team:
            return field
        team = self.names.bitmap(touchdown.fantasy_team).crop((0, 0, 62, self.names.HEIGHT))
        team_x, team_y = 2, 5
        original_x = round(-16 + 80 * frame_index / max(1, len(self.frames) - 1))
        runner_left = 48 - original_x if reverse else original_x
        if reverse:
            source_x = max(0, min(team.width, runner_left + 16 - team_x))
            revealed = team.crop((source_x, 0, team.width, team.height))
            field.paste(revealed, (team_x + source_x, team_y), revealed.convert("L"))
        else:
            visible_width = max(0, min(team.width, runner_left - team_x))
            revealed = team.crop((0, 0, visible_width, team.height))
            field.paste(revealed, (team_x, team_y), revealed.convert("L"))
        return field

    def render(self, touchdown, elapsed, duration):
        image = Image.new("RGB", (64, 32))
        progress = min(max(elapsed / duration, 0), 0.999999)
        frame_index = int(progress * len(self.frames))
        is_dst = touchdown.kind in {
            "INT TOUCHDOWN", "FUM TOUCHDOWN", "RETURN TOUCHDOWN",
        }
        image.paste(self._runner_field(touchdown, frame_index, is_dst), (0, 16))
        if touchdown.kind == "BIG PLAY":
            try:
                player_color = ImageColor.getrgb(touchdown.team_color or "#ffffff")
            except ValueError:
                player_color = (255, 255, 255)
            name_mask = self.names.bitmap(touchdown.name).convert("L")
            name_image = Image.new("RGB", name_mask.size, player_color)
            image.paste(name_image, ((64 - name_image.width) // 2, 1), name_mask)
            detail = f"{touchdown.yards} YD {touchdown.play_type}"
            label = self.names.bitmap(detail)
            image.paste(label, (max(0, (64 - label.width) // 2), 9))
        elif elapsed < duration / 2:
            # Keep the title visible, alternating yellow/orange every 250ms.
            mask = self.names.bitmap("TOUCHDOWN").convert("L")
            color = (255, 220, 0) if int(elapsed / 0.25) % 2 == 0 else (255, 128, 0)
            title = Image.new("RGB", mask.size, color)
            image.paste(title, ((64 - title.width) // 2, 5), mask)
        else:
            detail_time = elapsed - duration / 2
            name = self.names.bitmap(touchdown.name)
            try:
                player_color = ImageColor.getrgb(touchdown.team_color or "#ffffff")
            except ValueError:
                player_color = (255, 255, 255)
            if name.width <= 64:
                mask = name.convert("L")
                colored_name = Image.new("RGB", mask.size, player_color)
                image.paste(colored_name, ((64 - name.width) // 2, 1), mask)
            else:
                mask = self.names.window(touchdown.name, 64, int(detail_time * 16)).convert("L")
                colored_name = Image.new("RGB", mask.size, player_color)
                image.paste(colored_name, (0, 1), mask)
            detail = (f"{touchdown.yards} YD {touchdown.play_type}"
                      if touchdown.yards is not None and touchdown.play_type
                      else f"{touchdown.yards} YD TOUCHDOWN"
                      if touchdown.yards is not None else "TOUCHDOWN")
            label = self.names.bitmap(detail)
            image.paste(label, (max(0, (64 - label.width) // 2), 9))
        return image


if __name__ == "__main__":
    export_runner_gif()
    print(f"Wrote {ASSET}")
