"""<base href> honoring in the extractor and rewriter."""
from webui.link_rewrite import extract_html_refs, rewrite_html


def test_extract_applies_base_absolute_path():
    html = '''
    <html><head><base href="/products/"></head>
    <body><a href="foo.html">x</a><img src="img/a.gif"></body></html>
    '''
    refs = extract_html_refs(html)
    # Relative refs now absolutize against the base.
    assert "/products/foo.html" in refs
    assert "/products/img/a.gif" in refs


def test_extract_absolute_refs_ignore_base():
    html = '''
    <html><head><base href="/products/"></head>
    <body><a href="/news.html">x</a><a href="#top">y</a></body></html>
    '''
    refs = extract_html_refs(html)
    # Absolute path + fragment-only refs unchanged.
    assert "/news.html" in refs
    assert "#top" in refs
    # No false absolutization.
    assert "/products/news.html" not in refs


def test_rewrite_removes_base_tag():
    html = (
        '<html><head><base href="/products/"></head>'
        '<body><a href="foo.html">x</a></body></html>'
    )
    new, hits = rewrite_html(html, "")
    assert "<base" not in new.lower()
    assert hits >= 1


def test_rewrite_base_rewires_relative_to_absolute_path():
    # In a page stored at /nav/header.html, a <base href="/products/">
    # means "foo.html" resolves to /products/foo.html, not /nav/foo.html.
    # After rewrite, the href should point to the products/ tree.
    html = (
        '<html><head><base href="/products/"></head>'
        '<body><a href="foo.html">x</a></body></html>'
    )
    # Page "stored" at nav/header.html relative to snapshot root.
    new, _ = rewrite_html(html, "nav")
    # Expected: ../products/foo.html (up one from /nav, into /products).
    assert "../products/foo.html" in new


def test_rewrite_no_base_tag_unchanged():
    html = '<html><body><a href="/x.html">x</a></body></html>'
    new, hits = rewrite_html(html, "sub")
    assert "<base" not in new.lower()
    # Absolute-path rewrite to relative is the only change.
    assert "../x.html" in new
