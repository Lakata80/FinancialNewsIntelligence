from app.ingestion.canonical import canonicalize_url


def test_strips_utm_params():
    url = "https://example.com/article?utm_source=twitter&utm_medium=social&id=123"
    assert canonicalize_url(url) == "https://example.com/article?id=123"


def test_strips_tsrc():
    url = "https://finance.yahoo.com/news/foo.html?tsrc=fin-notif&bar=1"
    assert canonicalize_url(url) == "https://finance.yahoo.com/news/foo.html?bar=1"


def test_strips_yptr():
    url = "https://finance.yahoo.com/news/foo.html?yptr=yahoo&id=42"
    assert canonicalize_url(url) == "https://finance.yahoo.com/news/foo.html?id=42"


def test_strips_www_prefix():
    assert canonicalize_url("https://www.reuters.com/tech/story") == "https://reuters.com/tech/story"


def test_strips_fragment():
    url = "https://example.com/article#section2"
    assert "#" not in canonicalize_url(url)


def test_lowercases_scheme_and_host():
    url = "HTTPS://Example.COM/path"
    canon = canonicalize_url(url)
    assert canon.startswith("https://example.com/")


def test_empty_query_string():
    url = "https://example.com/article"
    assert canonicalize_url(url) == "https://example.com/article"


def test_trailing_slash_stripped():
    url = "https://example.com/article/"
    assert canonicalize_url(url) == "https://example.com/article"


def test_sorts_remaining_params():
    url = "https://example.com/a?z=1&a=2"
    assert canonicalize_url(url) == "https://example.com/a?a=2&z=1"


def test_two_urls_differing_only_by_tracking_become_equal():
    base = "https://finance.yahoo.com/news/story.html?id=100"
    with_tracking = "https://finance.yahoo.com/news/story.html?id=100&utm_source=yahoo&tsrc=rss"
    assert canonicalize_url(base) == canonicalize_url(with_tracking)


def test_strips_all_utm_variants():
    url = "https://example.com/a?utm_source=x&utm_medium=y&utm_campaign=z&utm_term=t&utm_content=c&utm_id=1"
    assert canonicalize_url(url) == "https://example.com/a"
