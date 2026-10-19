from tools.converter import github_slug, html_to_markdown

BASE = "https://help.example.com"


def md(html: str) -> str:
    return html_to_markdown(html, BASE)


def test_strips_closing_boilerplate():
    html = (
        "<h2>Setup</h2><p>Click Save.</p>"
        "<h3>That's all!</h3>"
        "<p>OptiSigns is the leader in digital signage software. If you have any additional "
        "questions, feel free to reach out to support@example.com</p>"
    )
    out = md(html)
    assert "Click Save." in out
    assert "That's all" not in out
    assert "leader in digital signage" not in out


def test_keeps_mid_article_text_that_looks_like_boilerplate():
    html = "<p>That's all! Congratulations.</p><h2>Next steps</h2><p>Assign it to a screen.</p>"
    out = md(html)
    assert "That's all! Congratulations." in out
    assert "Assign it to a screen." in out


def test_rewrites_in_page_anchor_to_heading_slug():
    html = (
        '<ul><li><a href="#WhatYoullNeed">What You\'ll Need</a></li></ul>'
        '<p><a name="WhatYoullNeed"></a></p><h2>What You\'ll Need</h2><p>A screen.</p>'
    )
    out = md(html)
    assert "[What You'll Need](#what-youll-need)" in out
    assert "## What You'll Need" in out
    assert "name=" not in out


def test_preserves_code_block_and_headings():
    html = '<h2>Install</h2><pre><code class="language-bash">curl -sL x | sh\n</code></pre><h3>Verify</h3>'
    out = md(html)
    assert "## Install" in out and "### Verify" in out
    assert "```bash\ncurl -sL x | sh" in out
    assert out.count("```") == 2


def test_single_column_table_becomes_callout_blockquote():
    html = "<figure><table><tr><td>NOTE</td></tr><tr><td>Requires the Pro plan.</td></tr></table></figure>"
    out = md(html)
    assert "> **NOTE:**" in out
    assert "> Requires the Pro plan." in out
    assert "|" not in out


def test_multi_column_table_stays_a_table():
    html = "<table><tr><th>Plan</th><th>Price</th></tr><tr><td>Pro</td><td>$10</td></tr></table>"
    out = md(html)
    assert "| Plan | Price |" in out


def test_absolutizes_root_relative_links_and_drops_noise():
    html = (
        '<p><span style="color:red">See <a href="/hc/articles/1" target="_blank">this</a></span></p>'
        '<p><img src="data:image/png;base64,AAAA"><img src="/a.png" alt=""></p>'
        '<p><img src="/b.png" alt="Apps button"></p>'
        '<iframe src="//www.youtube.com/embed/abc"></iframe>'
    )
    out = md(html)
    assert "[this](https://help.example.com/hc/articles/1)" in out
    assert "data:image" not in out and "a.png" not in out
    assert "![Apps button](https://help.example.com/b.png)" in out
    assert "[Embedded video](https://www.youtube.com/embed/abc)" in out
    assert "span" not in out and "style" not in out


def test_github_slug():
    assert github_slug("Step 3 (Optional): Use Parameters.") == "step-3-optional-use-parameters"
