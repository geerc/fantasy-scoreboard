import unittest
from PIL import Image, ImageChops

from name_scroll import NameRenderer
from touchdown_animation import CelebrationRenderer, runner_foot, runner_sprite, RUN_POSES, SHOE_WIDTH, SHOE_HEIGHT
from touchdowns import Touchdown
from test_scoreboard import PROJECT_DIR


class GaitTests(unittest.TestCase):
    def test_compact_stride_and_larger_shoes_without_heel_tuck(self):
        near, far, _ = RUN_POSES[0]
        self.assertEqual(near[1][0] - far[1][0], 7)
        self.assertEqual((SHOE_WIDTH, SHOE_HEIGHT), (4, 2))
        self.assertGreater(6 - far[1][0], near[1][0] - 6)
        self.assertLess(RUN_POSES[1][1][1][0], 3)
        for near, far, _ in RUN_POSES:
            for knee, foot in (near, far):
                self.assertGreaterEqual(foot[1], knee[1])
                self.assertLess(foot[0] + SHOE_WIDTH - 1, 16)
        # The front shoe in the split pose occupies a full 4x2 block.
        sprite = runner_sprite(0)
        for x in range(8, 12):
            for y in range(13, 15):
                self.assertEqual(sprite.getpixel((x, y)), (245, 245, 238, 255))

    def test_legs_alternate_and_body_bounces(self):
        for index in range(3):
            self.assertEqual(RUN_POSES[index][0], RUN_POSES[index + 3][1])
            self.assertEqual(RUN_POSES[index][1], RUN_POSES[index + 3][0])
        self.assertEqual({pose[2] for pose in RUN_POSES}, {0, 1})
        self.assertEqual(runner_foot(0), runner_foot(12))
        for tick in range(12):
            self.assertEqual(runner_sprite(tick).size, (16, 16))
        self.assertNotEqual(runner_sprite(0).tobytes(), runner_sprite(4).tobytes())

    def test_dst_runner_moves_and_faces_the_opposite_direction(self):
        names = NameRenderer(PROJECT_DIR / "rpi-rgb-led-matrix/fonts/4x6.bdf")
        renderer = CelebrationRenderer(names)
        offense = Touchdown("offense", "RB", "Runner", "RUSHING TD")
        defense = Touchdown("defense", "BUF", "BUF D/ST", "INT TOUCHDOWN")
        offense_field = renderer.render(offense, 1.25, 5).crop((0, 16, 64, 32))
        defense_field = renderer.render(defense, 1.25, 5).crop((0, 16, 64, 32))
        self.assertIsNone(ImageChops.difference(
            offense_field.transpose(Image.Transpose.FLIP_LEFT_RIGHT), defense_field
        ).getbbox())

    def test_detail_name_is_centered_and_long_names_still_scroll(self):
        names = NameRenderer(PROJECT_DIR / 'rpi-rgb-led-matrix/fonts/4x6.bdf')
        renderer = CelebrationRenderer(names)
        event = Touchdown('test', 'RB', 'Bucky Irving', 'RUSHING TD')
        frame = renderer.render(event, 2.5, 5)
        text = names.bitmap(event.name)
        x = (64 - text.width) // 2
        self.assertIsNone(frame.crop((0, 1, x, 7)).getbbox())
        self.assertIsNone(ImageChops.difference(text, frame.crop((x, 1, x + text.width, 7))).getbbox())
        long = Touchdown('long', 'WR', 'A Very Long Football Player Name', 'RECEIVING TD')
        first = renderer.render(long, 2.5, 5).crop((0, 1, 64, 7))
        later = renderer.render(long, 3.5, 5).crop((0, 1, 64, 7))
        self.assertIsNotNone(ImageChops.difference(first, later).getbbox())


if __name__ == '__main__':
    unittest.main()
