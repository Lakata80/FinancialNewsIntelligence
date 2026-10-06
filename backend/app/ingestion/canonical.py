from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "tsrc", "yptr", "ncid", "cmpid", "cid",
    # "ref", "source", "via" omitted — too broad for finance URLs
})


def canonicalize_url(raw: str) -> str:
    """Strip tracking params, normalize scheme/host, remove fragment."""
    parsed = urlparse(raw.strip())
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/") or "/"
    qs = urlencode(
        sorted(
            (k, v) for k, v in parse_qsl(parsed.query)
            if k.lower() not in _TRACKING_PARAMS
        )
    )
    # Fragment is always dropped (never part of canonical identity)
    return urlunparse((scheme, host, path, "", qs, ""))
