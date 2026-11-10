from insight.adapters.transforms.publication import publication_date


def test_explicit_paper_and_publisher_dates_do_not_use_modified_or_generic_times():
    for key in ("citation_date", "dcterms.issued", "parsely-pub-date"):
        assert publication_date(f'<meta name="{key}" content="2026-10-25">'.encode()) == "2026-10-25"
    assert publication_date(b'<meta itemprop="datePublished" content="2026-10-25">') == "2026-10-25"
    assert publication_date(b'<time itemprop="datePublished" datetime="2026-10-25">October 25</time>') == "2026-10-25"
    assert publication_date(b'<time pubdate datetime="2026-10-25"></time>') == "2026-10-25"
    assert publication_date(b'<time datetime="2026-10-25"></time>') is None
    assert publication_date(b'<meta itemprop="dateModified" content="2026-10-25">') is None
    assert publication_date(b'<meta name="citation_date" content="2026-10-25"><time pubdate datetime="2026-10-26"></time>') is None


def test_only_explicit_unambiguous_publication_metadata_is_used():
    assert (
        publication_date(b'<meta property="article:published_time" content="2026-10-25T12:00:00Z">')
        == "2026-10-25"
    )
    assert (
        publication_date(b'<meta name="citation_publication_date" content="2026/10/25">')
        == "2026-10-25"
    )
    assert (
        publication_date(
            b'<script type="application/ld+json">{"@graph":[{"datePublished":"2026-10-25"}]}</script>'
        )
        == "2026-10-25"
    )
    assert publication_date(b'<meta property="article:modified_time" content="2026-10-25">') is None
    assert publication_date(b"<p>Copyright 2026. Retrieved 2026-10-25.</p>") is None
    assert (
        publication_date(b'<meta property="article:published_time" content="2026-02-30">') is None
    )
    assert (
        publication_date(
            b'<meta property="article:published_time" content="2026-10-25"><meta name="citation_publication_date" content="2026-10-26">'
        )
        is None
    )
