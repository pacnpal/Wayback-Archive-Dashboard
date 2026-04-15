"""NCSA imagemap parser + point-in-shape + viewer + link-rewrite behavior."""
from webui.imagemap import (
    Shape, parse_map, resolve, parse_query_coords, is_plausible_map_text,
)


SAMPLE = """\
# Top-nav imagemap
default http://www.example.com/

rect    http://www.example.com/products 0,0 100,50
rect    http://www.example.com/support  100,0 200,50
poly    http://www.example.com/news     10,60 90,60 50,150
circle  http://www.example.com/contact  150,100 150,120
point   http://www.example.com/tip      40,40
"""


def test_parse_sample():
    shapes = parse_map(SAMPLE)
    kinds = [s.kind for s in shapes]
    assert kinds == ["default", "rect", "rect", "poly", "circle", "point"]
    assert shapes[0].url == "http://www.example.com/"
    assert shapes[1].coords == [(0, 0), (100, 50)]
    assert shapes[3].coords == [(10, 60), (90, 60), (50, 150)]
    assert shapes[4].coords == [(150, 100), (150, 120)]


def test_parse_skips_comments_and_blanks():
    text = "\n\n  # leading comment\n\nrect http://x/y 0,0 10,10\n# trailing\n"
    shapes = parse_map(text)
    assert len(shapes) == 1
    assert shapes[0].url == "http://x/y"


def test_parse_inline_comment():
    shapes = parse_map("rect http://x/y 0,0 10,10  # click me\n")
    assert shapes[0].coords == [(0, 0), (10, 10)]


def test_parse_ignores_bad_lines():
    # `bogus` is not a shape keyword → skipped.
    shapes = parse_map("bogus http://x/y 0,0 10,10\nrect http://x/z 0,0 5,5\n")
    assert [s.kind for s in shapes] == ["rect"]


def test_resolve_rect_hit():
    shapes = parse_map(SAMPLE)
    # (50, 25) is inside the products rect (0,0)-(100,50).
    assert resolve(shapes, 50, 25) == "http://www.example.com/products"


def test_resolve_rect_boundary():
    shapes = parse_map("rect http://x/y 10,20 50,60\n")
    assert resolve(shapes, 10, 20) == "http://x/y"
    assert resolve(shapes, 50, 60) == "http://x/y"
    assert resolve(shapes, 9, 20) is None      # outside by 1 px
    assert resolve(shapes, 50, 61) is None


def test_resolve_circle():
    # Isolated circle sample (no point/default fallback) so the miss is clean.
    shapes = parse_map("circle http://x/c 150,100 150,120\n")
    assert resolve(shapes, 150, 100) == "http://x/c"
    assert resolve(shapes, 165, 100) == "http://x/c"  # dist=15
    assert resolve(shapes, 175, 100) is None           # dist=25 > 20


def test_resolve_poly_concave():
    # Hockey-stick / backwards-L: bottom half full width + upper-right
    # square. The upper-left quadrant is the notched-out region.
    concave = """
    poly http://x/concave 0,0 50,0 50,50 25,50 25,25 0,25
    """
    shapes = parse_map(concave)
    # Inside the bottom (full-width) bar.
    assert resolve(shapes, 10, 10) == "http://x/concave"
    # Inside the upper-right square.
    assert resolve(shapes, 40, 40) == "http://x/concave"
    # In the bottom strip (below notch).
    assert resolve(shapes, 40, 15) == "http://x/concave"
    # In the notched-out upper-left quadrant → outside.
    assert resolve(shapes, 10, 40) is None


def test_resolve_default_fallback():
    shapes = parse_map("default http://x/home\nrect http://x/foo 0,0 10,10\n")
    assert resolve(shapes, 100, 100) == "http://x/home"


def test_resolve_point_nearest_neighbor():
    text = "point http://x/a 10,10\npoint http://x/b 90,90\n"
    shapes = parse_map(text)
    assert resolve(shapes, 20, 20) == "http://x/a"
    assert resolve(shapes, 80, 80) == "http://x/b"


def test_resolve_rect_beats_point_priority():
    # NCSA semantics: hard shapes win before point nearest-neighbor.
    text = "point http://x/p 0,0\nrect http://x/r 10,10 50,50\n"
    shapes = parse_map(text)
    assert resolve(shapes, 20, 20) == "http://x/r"
    # Outside the rect, the point fires.
    assert resolve(shapes, 100, 100) == "http://x/p"


def test_resolve_no_match_no_default():
    shapes = parse_map("rect http://x/y 0,0 10,10\n")
    assert resolve(shapes, 100, 100) is None


def test_parse_query_coords():
    assert parse_query_coords("271,142") == (271, 142)
    assert parse_query_coords(" 10 , 20 ") == (10, 20)
    assert parse_query_coords("foo") is None
    assert parse_query_coords("") is None


def test_is_plausible_map_text_accepts():
    assert is_plausible_map_text(b"rect http://x 0,0 10,10\n")
    assert is_plausible_map_text(b"# comment\ndefault http://x\n")
    assert is_plausible_map_text(b"\n\n  circle http://x 10,10 15,15\n")


def test_is_plausible_map_text_rejects_html():
    assert not is_plausible_map_text(b"<!DOCTYPE html><html>")
    assert not is_plausible_map_text(b"<script>alert(1)</script>")
    assert not is_plausible_map_text(b"")
    assert not is_plausible_map_text(b"some random text")
