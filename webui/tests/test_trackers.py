"""Archive-time tracker stripping + no-referrer meta injection."""
from webui.link_rewrite import rewrite_html


def test_strip_google_analytics():
    html = (
        '<html><head>'
        '<script src="https://www.google-analytics.com/analytics.js"></script>'
        '</head><body></body></html>'
    )
    new, _ = rewrite_html(html, "")
    assert "google-analytics" not in new
    # The no-referrer meta is injected.
    assert 'name="referrer"' in new.lower()
    assert 'no-referrer' in new.lower()


def test_strip_multiple_trackers():
    html = (
        '<html><head>'
        '<script src="https://www.googletagmanager.com/gtm.js?id=GTM-X"></script>'
        '<script src="https://connect.facebook.net/en_US/sdk.js"></script>'
        '<script src="https://static.hotjar.com/c/hotjar-123.js"></script>'
        '</head></html>'
    )
    new, _ = rewrite_html(html, "")
    assert "googletagmanager" not in new
    assert "facebook.net" not in new
    assert "hotjar" not in new


def test_keep_site_scripts():
    html = (
        '<html><head>'
        '<script src="/js/app.js"></script>'
        '<script src="https://www.example.com/lib.js"></script>'
        '</head></html>'
    )
    new, _ = rewrite_html(html, "")
    assert "/js/app.js" in new or "js/app.js" in new
    # Non-tracker third-party script is kept (user controls what's in their archive).
    assert "example.com/lib.js" in new


def test_referrer_meta_injected_once():
    html = '<html><head><title>x</title></head><body>y</body></html>'
    new, _ = rewrite_html(html, "")
    # Exactly one referrer meta inserted.
    assert new.lower().count('name="referrer"') == 1


def test_referrer_meta_idempotent():
    # If the page already declares a referrer policy, we don't add another.
    html = (
        '<html><head><meta name="referrer" content="origin">'
        '<title>x</title></head><body></body></html>'
    )
    new, _ = rewrite_html(html, "")
    assert new.lower().count('name="referrer"') == 1
    # The existing policy is preserved (not overwritten).
    assert 'content="origin"' in new.lower()
