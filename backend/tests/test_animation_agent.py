from app.services.animation_agent import AnimationAgent


def make_agent() -> AnimationAgent:
    return AnimationAgent.__new__(AnimationAgent)


def test_sanitize_svg_repairs_unclosed_leaf_tags_and_infers_viewbox():
    raw = """<svg>
      <rect width="800" height="520" fill="#f8f9fa">
      <text x="400" y="40">Visible title</text>
      <line x1="0" y1="80" x2="800" y2="80" stroke="#333">
    </svg>"""

    sanitized = make_agent().sanitize_svg(raw)

    assert 'viewBox="0 0 800 520"' in sanitized
    assert '<rect width="800" height="520" fill="#f8f9fa" />' in sanitized
    assert '<line x1="0" y1="80" x2="800" y2="80" stroke="#333" />' in sanitized
    assert sanitized.index('/>') < sanitized.index('<text')


def test_sanitize_svg_preserves_canonical_viewbox_and_removes_leaf_closers():
    raw = '<svg viewBox="0 0 640 320"><path d="M 0 0 L 10 10"></path></svg>'

    sanitized = make_agent().sanitize_svg(raw)

    assert 'viewBox="0 0 640 320"' in sanitized
    assert '<path d="M 0 0 L 10 10" />' in sanitized
    assert '</path>' not in sanitized


def test_sanitize_svg_inlines_safe_class_styles_and_removes_css_text():
    raw = """<svg viewBox="0 0 640 320">
      <style>.box{fill:#e3f2fd;stroke:#1565c0;stroke-width:1.5}.label{font-size:14px;fill:#222;text-anchor:middle}</style>
      <rect class="box" x="20" y="20" width="200" height="60"></rect>
      <text class="label" x="120" y="50">Visible</text>
    </svg>"""

    sanitized = make_agent().sanitize_svg(raw)

    assert ".box{" not in sanitized
    assert "<style" not in sanitized
    assert 'fill="#e3f2fd"' in sanitized
    assert 'stroke="#1565c0"' in sanitized
    assert 'font-size="14px"' in sanitized
    assert 'text-anchor="middle"' in sanitized


def test_sanitize_svg_repairs_legacy_stripped_css_and_expands_clipped_viewbox():
    raw = """<svg viewBox="0 0 640 420">
      .box{fill:#f8f9fa;stroke:#333}.text{font-size:13px;text-anchor:middle}
      <rect x="230" y="395" width="180" height="46"></rect>
      <text x="320" y="433">Context vector</text>
      <text x="320" y="300">softmax</text>
    </svg>"""

    sanitized = make_agent().sanitize_svg(raw)

    assert ".box{" not in sanitized
    assert 'viewBox="0 0 640 453"' in sanitized
    assert 'fill="#f8fafc"' in sanitized
    assert 'text-anchor="middle"' in sanitized
    assert 'paint-order="stroke"' in sanitized
    assert 'stroke="#ffffff"' in sanitized
