"""Tests for the engine layer."""

from __future__ import annotations

import json
import unittest

from ascii_warriors.engine import colors, geometry, keys
from ascii_warriors.engine.fov import compute_fov, fov_set, has_los, line_of_fire
from ascii_warriors.engine.noise import (
    DiamondSquare, ValueNoise, normalize_grid, smooth_grid,
)
from ascii_warriors.engine.pathfind import DijkstraMap, astar, dijkstra, nearest
from ascii_warriors.engine.rng import RNG, seed_from_string
from ascii_warriors.engine.scheduler import ACTION_COST, Scheduler
from ascii_warriors.engine.screen import (
    Frag, Screen, frag_slice, frag_str, parse_markup, wrap, wrap_frags,
)
from ascii_warriors.engine.terminal import (
    HeadlessTerminal, QuitSignal, Terminal, decode_key, decode_windows_key,
    detect_color_mode, to_ascii,
)
from ascii_warriors.engine.widgets import ListMenu, MenuItem, choose, header, popup


class TestColors(unittest.TestCase):
    def test_hex_parsing(self):
        self.assertEqual(colors.hexc("#ff8800"), colors.Color(255, 136, 0))
        self.assertEqual(colors.hexc("ff8800"), colors.Color(255, 136, 0))
        self.assertEqual(colors.hexc("f80"), colors.Color(255, 136, 0))
        with self.assertRaises(ValueError):
            colors.hexc("nope")

    def test_quantisation_extremes(self):
        self.assertIn(colors.to_256(colors.BLACK), (0, 16))
        self.assertIn(colors.to_256(colors.WHITE), (15, 231))
        self.assertEqual(colors.to_16(colors.BLACK), 0)
        for c in (colors.RED, colors.GREEN, colors.BLUE, colors.GOLD):
            self.assertTrue(0 <= colors.to_256(c) <= 255)
            self.assertTrue(0 <= colors.to_16(c) <= 15)

    def test_grey_ramp_prefers_greyscale(self):
        grey = colors.Color(128, 128, 128)
        idx = colors.to_256(grey)
        self.assertTrue(232 <= idx <= 255 or 16 <= idx <= 231 or idx < 16)

    def test_blend_and_clamp(self):
        self.assertEqual(colors.blend(colors.BLACK, colors.WHITE, 0.0), colors.BLACK)
        self.assertEqual(colors.blend(colors.BLACK, colors.WHITE, 1.0), colors.WHITE)
        mid = colors.blend(colors.BLACK, colors.WHITE, 0.5)
        self.assertTrue(120 <= mid.r <= 135)
        self.assertEqual(colors.darken(colors.WHITE, 0.0), colors.BLACK)
        self.assertEqual(colors.darken(colors.WHITE, 1.0), colors.WHITE)
        self.assertEqual(colors.rgb(-10, 300, 40), colors.Color(0, 255, 40))

    def test_ui_palette_complete(self):
        required = (
            "bg fg dim accent accent2 warn danger good frame frame_hi title "
            "select_bg select_fg shadow".split()
        )
        for key in required:
            self.assertIn(key, colors.UI)


class TestKeys(unittest.TestCase):
    def test_direction_tables(self):
        for k in "hjklyubn":
            self.assertIn(k, keys.DIR_KEYS)
        for k in (keys.UP, keys.DOWN, keys.LEFT, keys.RIGHT):
            self.assertIn(k, keys.DIR_KEYS)
        self.assertEqual(keys.DIR_KEYS["5"], (0, 0))
        self.assertEqual(keys.direction_of("H"), (-1, 0))
        self.assertTrue(keys.is_run_key("J"))
        self.assertFalse(keys.is_run_key("j"))

    def test_helpers(self):
        self.assertTrue(keys.is_printable("a"))
        self.assertFalse(keys.is_printable(keys.ENTER))
        self.assertEqual(keys.shifted("1"), "!")
        self.assertEqual(keys.ctrl("S"), "C-s")
        self.assertEqual(keys.key_label(keys.PGUP), "PgUp")
        self.assertEqual(keys.key_label("C-s"), "Ctrl-S")


class TestRNG(unittest.TestCase):
    def test_determinism(self):
        a, b = RNG("seed"), RNG("seed")
        self.assertEqual(
            [a.randint(0, 10 ** 6) for _ in range(100)],
            [b.randint(0, 10 ** 6) for _ in range(100)],
        )
        self.assertNotEqual(RNG("a").random(), RNG("b").random())

    def test_seed_from_string_stable(self):
        self.assertEqual(seed_from_string("Urist"), seed_from_string("Urist"))
        self.assertNotEqual(seed_from_string("a"), seed_from_string("b"))

    def test_sub_streams_independent_of_consumption(self):
        a, b = RNG(11), RNG(11)
        for _ in range(500):
            a.random()
        self.assertEqual(a.sub("world").randint(0, 10 ** 9),
                         b.sub("world").randint(0, 10 ** 9))
        self.assertNotEqual(a.sub("world").seed, a.sub("other").seed)

    def test_state_round_trip_through_json(self):
        r = RNG("x")
        r.randint(0, 100)
        data = json.loads(json.dumps(r.to_dict()))
        clone = RNG.from_dict(data)
        self.assertEqual([r.randint(0, 10 ** 9) for _ in range(20)],
                         [clone.randint(0, 10 ** 9) for _ in range(20)])

    def test_weighted_ignores_zero_weights(self):
        r = RNG(1)
        for _ in range(50):
            self.assertEqual(r.weighted({"a": 0, "b": 0, "c": 5}), "c")
        with self.assertRaises(ValueError):
            r.weighted({"a": 0})

    def test_roll_bounds(self):
        r = RNG(2)
        for _ in range(200):
            v = r.roll(3, 6)
            self.assertTrue(3 <= v <= 18)
        self.assertEqual(r.roll(0, 6), 0)

    def test_pick_index(self):
        r = RNG(3)
        self.assertEqual(r.pick_index([0, 0, 1]), 2)
        self.assertEqual(r.pick_index([0, 0, 0]), -1)


class TestGeometry(unittest.TestCase):
    def test_rect(self):
        r = geometry.Rect(2, 3, 4, 5)
        self.assertTrue(r.contains(2, 3))
        self.assertFalse(r.contains(6, 3))
        self.assertEqual(r.area, 20)
        self.assertEqual(len(list(r.cells())), 20)
        self.assertEqual(r.expand(1).as_tuple(), (1, 2, 6, 7))
        self.assertEqual(r.clamp_point(0, 0), geometry.Point(2, 3))
        self.assertTrue(r.intersects(geometry.Rect(5, 7, 3, 3)))
        self.assertFalse(r.intersects(geometry.Rect(20, 20, 2, 2)))

    def test_line_endpoints_and_symmetry(self):
        pts = geometry.line(0, 0, 5, 3)
        self.assertEqual(pts[0], (0, 0))
        self.assertEqual(pts[-1], (5, 3))
        back = geometry.line(5, 3, 0, 0)
        self.assertEqual(set(pts), set(back))
        self.assertEqual(geometry.line(4, 4, 4, 4), [geometry.Point(4, 4)])

    def test_circle_and_ring(self):
        self.assertEqual(len(geometry.circle(0, 0, 0)), 1)
        self.assertTrue(len(geometry.circle(0, 0, 3)) > len(geometry.ring(0, 0, 3)))
        for p in geometry.ring(0, 0, 4):
            self.assertTrue(3 <= geometry.euclid(0, 0, p.x, p.y) <= 5)

    def test_directions(self):
        self.assertEqual(geometry.direction_name(1, 1), "southeast")
        self.assertEqual(geometry.direction_name(0, -1), "north")
        self.assertEqual(geometry.direction_name(0, 0), "here")
        self.assertEqual(geometry.normalize_dir(-7, 3), (-1, 1))
        self.assertEqual(geometry.direction_abbrev(-1, 0), "W")

    def test_bresenham_3d(self):
        path = geometry.bresenham_3d(0, 0, 0, 3, 5, 2)
        self.assertEqual(path[0], (0, 0, 0))
        self.assertEqual(path[-1], (3, 5, 2))

    def test_flood_fill(self):
        cells = geometry.flood_fill(
            (0, 0), lambda x, y: 0 <= x < 4 and 0 <= y < 4
        )
        self.assertEqual(len(cells), 16)

    def test_rect_of_points(self):
        r = geometry.rect_of_points([(1, 2), (5, 7), (3, 3)])
        self.assertEqual(r.as_tuple(), (1, 2, 5, 6))


class TestScreen(unittest.TestCase):
    def setUp(self):
        self.scr = Screen(20, 6)
        self.scr.clear()

    def test_clipping_never_raises(self):
        for x, y in ((-5, -5), (100, 100), (-1, 3), (3, -1), (19, 5)):
            self.scr.put(x, y, "X")
        self.scr.fill(-10, -10, 100, 100, "#")
        self.scr.frame(-2, -2, 40, 40)
        self.scr.blit(Screen(50, 50), -10, -10)
        self.assertEqual(len(self.scr.to_text()), 6)

    def test_text_widths(self):
        self.assertEqual(self.scr.text(0, 0, "hello"), 5)
        self.assertEqual(self.scr.text(18, 0, "hello"), 2)
        self.assertEqual(self.scr.text(0, 99, "hello"), 0)
        self.assertEqual(self.scr.text(0, 1, "hello", max_width=3), 3)

    def test_wrap(self):
        self.assertEqual(wrap("aaa bbb ccc", 7), ["aaa bbb", "ccc"])
        self.assertEqual(wrap("abcdefghij", 4), ["abcd", "efgh", "ij"])
        self.assertEqual(wrap("", 5), [""])
        self.assertEqual(wrap("a\nb", 5), ["a", "b"])

    def test_wrapped_preserves_colors_and_limits(self):
        markup = [Frag("hello ", colors.RED), Frag("world again", colors.BLUE)]
        lines = wrap_frags(markup, 7)
        self.assertGreaterEqual(len(lines), 2)
        self.assertEqual(frag_str(lines[0]), "hello")
        self.assertEqual(lines[0][0].color, colors.RED)
        used = self.scr.wrapped(0, 0, 8, markup, max_lines=2)
        self.assertEqual(used, 2)

    def test_frag_slice(self):
        out = frag_slice([Frag("abcdef", colors.RED)], 2, 4)
        self.assertEqual(frag_str(out), "cd")

    def test_parse_markup(self):
        frags = parse_markup("a {red}b{/} c")
        self.assertEqual(frag_str(frags), "a b c")
        self.assertEqual(len(frags), 3)

    def test_frame_and_shade(self):
        self.scr.frame(0, 0, 10, 4, title="Hi")
        ch, _fg, _bg = self.scr.get(0, 0)
        self.assertEqual(ch, "+")
        self.scr.fill(0, 0, 20, 6, "#", colors.WHITE, colors.WHITE)
        self.scr.shade(0, 0, 20, 6, 0.5)
        _ch, fg, _bg2 = self.scr.get(1, 1)
        self.assertLess(fg.r, 255)

    def test_snapshot_and_sub(self):
        self.scr.text(0, 0, "abc")
        snap = self.scr.snapshot()
        self.scr.text(0, 0, "xyz")
        self.assertEqual(snap.to_text()[0][:3], "abc")
        self.assertEqual(self.scr.sub(0, 0, 3, 1).to_text(), ["xyz"])


class TestNoise(unittest.TestCase):
    def test_ranges_and_determinism(self):
        n = ValueNoise(RNG("n"))
        values = [n.noise2(x * 0.3, y * 0.3) for x in range(20) for y in range(20)]
        self.assertTrue(all(-1.001 <= v <= 1.001 for v in values))
        self.assertLess(min(values), 0.0)
        self.assertGreater(max(values), 0.0)
        for _ in range(5):
            self.assertTrue(0.0 <= n.ridged(1.1, 2.2) <= 1.0)
            self.assertTrue(0.0 <= n.billow(1.1, 2.2) <= 1.0)
            self.assertTrue(-1.001 <= n.fbm(1.1, 2.2) <= 1.001)
        self.assertEqual(ValueNoise(RNG(9)).fbm(1.5, 2.5),
                         ValueNoise(RNG(9)).fbm(1.5, 2.5))

    def test_diamond_square(self):
        grid = DiamondSquare(RNG(4), 4).generate()
        self.assertEqual(len(grid), 17)
        self.assertEqual(len(grid[0]), 17)
        flat = [v for row in grid for v in row]
        self.assertAlmostEqual(min(flat), 0.0, places=6)
        self.assertAlmostEqual(max(flat), 1.0, places=6)

    def test_grid_helpers(self):
        grid = [[1.0, 3.0], [5.0, 7.0]]
        normalize_grid(grid)
        self.assertAlmostEqual(min(min(r) for r in grid), 0.0)
        self.assertAlmostEqual(max(max(r) for r in grid), 1.0)
        smooth_grid(grid, 1)
        flat = [[2.0, 2.0], [2.0, 2.0]]
        normalize_grid(flat)
        self.assertEqual(flat, [[0.5, 0.5], [0.5, 0.5]])


class TestPathfind(unittest.TestCase):
    W, H = 20, 10

    def neighbours(self, node, walls=frozenset()):
        x, y = node
        for dx, dy in geometry.DIRS8:
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.W and 0 <= ny < self.H and (nx, ny) not in walls:
                yield ((nx, ny), 1.41 if dx and dy else 1.0)

    def test_open_path_is_direct(self):
        path = astar((0, 0), (5, 0), self.neighbours,
                     lambda a, b: geometry.chebyshev(a[0], a[1], b[0], b[1]))
        self.assertEqual(path[0], (0, 0))
        self.assertEqual(path[-1], (5, 0))
        self.assertEqual(len(path), 6)

    def test_routes_around_obstacle(self):
        walls = {(10, y) for y in range(0, 8)}
        path = astar((0, 0), (19, 0), lambda n: self.neighbours(n, walls),
                     lambda a, b: geometry.chebyshev(a[0], a[1], b[0], b[1]))
        self.assertIsNotNone(path)
        self.assertTrue(any(y >= 8 for _x, y in path))

    def test_unreachable_returns_none(self):
        walls = {(10, y) for y in range(self.H)}
        self.assertIsNone(astar(
            (0, 0), (19, 0), lambda n: self.neighbours(n, walls),
            lambda a, b: geometry.chebyshev(a[0], a[1], b[0], b[1])))

    def test_max_nodes_respected(self):
        self.assertIsNone(astar(
            (0, 0), (19, 9), self.neighbours,
            lambda a, b: 0.0, max_nodes=3))

    def test_dijkstra_map_descends_and_flees(self):
        dm = DijkstraMap.build([(5, 5)], self.neighbours)
        step = dm.best_step((9, 5), self.neighbours)
        self.assertLess(dm.value(step), dm.value((9, 5)))
        away = dm.best_step((9, 5), self.neighbours, flee=True)
        self.assertGreater(dm.value(away), dm.value((9, 5)))
        self.assertIsNone(dm.value((999, 999)))

    def test_works_with_3d_nodes(self):
        def nb3(node):
            x, y, z = node
            for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0),
                      (0, 0, 1), (0, 0, -1)):
                yield ((x + d[0], y + d[1], z + d[2]), 1.0)

        path = astar((0, 0, 0), (2, 2, 2), nb3,
                     lambda a, b: sum(abs(a[i] - b[i]) for i in range(3)))
        self.assertEqual(path[-1], (2, 2, 2))

    def test_nearest(self):
        self.assertEqual(
            nearest((0, 0), self.neighbours, lambda n: n == (4, 4)), (4, 4))
        self.assertIsNone(
            nearest((0, 0), self.neighbours, lambda n: n == (99, 99)))

    def test_dijkstra_distances(self):
        dist = dijkstra([(0, 0)], self.neighbours)
        self.assertEqual(dist[(0, 0)], 0.0)
        self.assertAlmostEqual(dist[(3, 0)], 3.0)


class TestFov(unittest.TestCase):
    def test_origin_always_visible(self):
        seen = fov_set(5, 5, 0, lambda x, y: True)
        self.assertIn((5, 5), seen)

    def test_wall_casts_shadow(self):
        blocked = {(5, 5)}
        seen = fov_set(3, 5, 8, lambda x, y: (x, y) in blocked)
        self.assertIn((5, 5), seen)
        self.assertNotIn((8, 5), seen)

    def test_radius_respected(self):
        seen = fov_set(0, 0, 3, lambda x, y: False)
        for x, y in seen:
            self.assertLessEqual(geometry.euclid(0, 0, x, y), 3.2)

    def test_los_endpoints_not_blockers(self):
        self.assertTrue(has_los(0, 0, 3, 0, lambda x, y: x == 3))
        self.assertFalse(has_los(0, 0, 6, 0, lambda x, y: x == 3))
        self.assertTrue(has_los(2, 2, 2, 2, lambda x, y: True))

    def test_line_of_fire_stops_at_blocker(self):
        path = line_of_fire(0, 0, 9, 0, lambda x, y: x == 4)
        self.assertEqual(path[-1], (4, 0))

    def test_intensity_decreases(self):
        seen = {}
        compute_fov(0, 0, 6, lambda x, y: False,
                    lambda x, y, i: seen.__setitem__((x, y), i))
        self.assertAlmostEqual(seen[(0, 0)], 1.0)
        self.assertLess(seen[(5, 0)], seen[(1, 0)])


class TestScheduler(unittest.TestCase):
    def test_speed_ratio(self):
        s = Scheduler()
        s.add(1, 100)
        s.add(2, 200)
        counts = {1: 0, 2: 0}
        for _ in range(600):
            a = s.next_actor()
            counts[a] += 1
            s.spend(a, ACTION_COST)
        self.assertGreater(counts[2] / counts[1], 1.8)
        self.assertLess(counts[2] / counts[1], 2.2)

    def test_priority_breaks_ties(self):
        s = Scheduler()
        s.add(1, 100)
        s.add(2, 100, priority=1)
        self.assertEqual(s.next_actor(), 2)

    def test_membership(self):
        s = Scheduler()
        self.assertIsNone(s.next_actor())
        s.add(7, 100)
        self.assertTrue(s.contains(7))
        s.set_speed(7, 50)
        self.assertEqual(s.speed_of(7), 50)
        s.remove(7)
        self.assertFalse(s.contains(7))
        s.remove(999)

    def test_round_trip(self):
        s = Scheduler()
        s.add(1, 120)
        s.next_actor()
        clone = Scheduler.from_dict(json.loads(json.dumps(s.to_dict())))
        self.assertEqual(clone.ticks, s.ticks)
        self.assertEqual(clone.speed_of(1), 120)

    def test_peek_order(self):
        s = Scheduler()
        s.add(1, 100)
        s.add(2, 300)
        order = s.peek_order(8)
        self.assertEqual(len(order), 8)
        self.assertGreater(order.count(2), order.count(1))


class TestTerminal(unittest.TestCase):
    def test_decode_arrows_and_specials(self):
        self.assertEqual(decode_key("\x1b[A"), (keys.UP, 3))
        self.assertEqual(decode_key("\x1b[B"), (keys.DOWN, 3))
        self.assertEqual(decode_key("\x1b[C"), (keys.RIGHT, 3))
        self.assertEqual(decode_key("\x1b[D"), (keys.LEFT, 3))
        self.assertEqual(decode_key("\x1b[H"), (keys.HOME, 3))
        self.assertEqual(decode_key("\x1b[5~"), (keys.PGUP, 4))
        self.assertEqual(decode_key("\x1b[6~"), (keys.PGDN, 4))
        self.assertEqual(decode_key("\x1b[3~"), (keys.DELETE, 4))
        self.assertEqual(decode_key("\x1b[15~"), (keys.F5, 5))
        self.assertEqual(decode_key("\x1bOP"), (keys.F1, 3))
        self.assertEqual(decode_key("\x1b[1;5C")[0], keys.RIGHT)
        self.assertEqual(decode_key("\x1b[Z"), (keys.BACKTAB, 3))

    def test_decode_incomplete_and_plain(self):
        self.assertEqual(decode_key(""), (None, 0))
        self.assertEqual(decode_key("\x1b"), (None, 0))
        self.assertEqual(decode_key("\x1b["), (None, 0))
        self.assertEqual(decode_key("a"), ("a", 1))
        self.assertEqual(decode_key("\r"), (keys.ENTER, 1))
        self.assertEqual(decode_key("\t"), (keys.TAB, 1))
        self.assertEqual(decode_key(" "), (keys.SPACE, 1))
        self.assertEqual(decode_key("\x7f"), (keys.BACKSPACE, 1))
        self.assertEqual(decode_key("\x13"), ("C-s", 1))

    def test_windows_decoder(self):
        self.assertEqual(decode_windows_key("H", True), keys.UP)
        self.assertEqual(decode_windows_key("P", True), keys.DOWN)
        self.assertEqual(decode_windows_key(";", True), keys.F1)
        self.assertEqual(decode_windows_key("\r", False), keys.ENTER)
        self.assertEqual(decode_windows_key("x", False), "x")

    def test_close_is_safe(self):
        t = Terminal()
        t.close()
        t.close()

    def test_headless_driver(self):
        term = HeadlessTerminal(30, 5, ["a", keys.ENTER])
        term.open()
        scr = Screen(30, 5)
        scr.clear()
        scr.text(0, 0, "frame")
        term.render(scr)
        self.assertEqual(term.read_key(), "a")
        self.assertEqual(term.read_key(), keys.ENTER)
        with self.assertRaises(QuitSignal):
            term.read_key()
        self.assertTrue(term.last_text().startswith("frame"))
        term.close()

    def test_headless_loops_when_asked(self):
        term = HeadlessTerminal(10, 3, ["a"], loop_keys=True)
        self.assertEqual(term.read_key(), "a")
        self.assertEqual(term.read_key(), "a")

    def test_diff_segments(self):
        w = 10
        chars = list("aaaaaaaaaa")
        fgs = [colors.RED] * w
        bgs = [colors.BLACK] * w
        pc, pf, pb = list(chars), list(fgs), list(bgs)
        seg = Terminal._row_segments
        self.assertEqual(seg(0, w, chars, fgs, bgs, pc, pf, pb, False, 4), [])
        chars[3] = "b"
        self.assertEqual(seg(0, w, chars, fgs, bgs, pc, pf, pb, False, 4), [(3, 4)])
        self.assertEqual(seg(0, w, chars, fgs, bgs, pc, pf, pb, True, 4), [(0, 10)])

    def test_ascii_fallback(self):
        self.assertEqual(to_ascii("a"), "a")
        self.assertEqual(to_ascii("─"), "-")
        self.assertEqual(to_ascii(""), " ")

    def test_color_mode_detection_runs(self):
        self.assertIn(detect_color_mode(),
                      ("auto", "truecolor", "256", "16", "mono"))


class TestWidgets(unittest.TestCase):
    def test_menu_navigation_skips_disabled(self):
        items = [header("Group"), MenuItem("Alpha", "a"), MenuItem("Beta", "b"),
                 MenuItem("Off", "c", enabled=False)]
        menu = ListMenu(items, per_page=8)
        self.assertEqual(menu.selected_value, "a")
        menu.handle("j")
        self.assertEqual(menu.selected_value, "b")
        menu.handle("j")
        self.assertEqual(menu.selected_value, "a")
        self.assertEqual(menu.handle(keys.ESC), "cancel")

    def test_menu_hotkeys_and_filter(self):
        menu = ListMenu([MenuItem("Alpha", "a"), MenuItem("Beta", "b")])
        hot = menu.items[1].hotkey
        self.assertEqual(menu.handle(hot), "select")
        self.assertEqual(menu.selected_value, "b")
        menu.set_filter("alp")
        self.assertEqual(len(menu.visible_items()), 1)

    def test_modal_choose_and_popup(self):
        scr = Screen(60, 20)
        scr.clear()
        term = HeadlessTerminal(60, 20, ["j", keys.ENTER])
        value = choose(scr, term, "Pick", [MenuItem("One", 1), MenuItem("Two", 2)])
        self.assertEqual(value, 2)
        term2 = HeadlessTerminal(60, 20, [keys.ENTER])
        self.assertEqual(popup(scr, term2, ["hello"], buttons=("OK",)), 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
