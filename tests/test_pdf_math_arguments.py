import pytest
import fitz

from studyforge.document_render import mathtext_arguments, math_image
from studyforge.exporters import export_document


@pytest.mark.parametrize('source,expected', [
    (r'\sqrt2', r'\sqrt{2}'),
    (r'\sqrt23', r'\sqrt{2}3'),
    (r'\sqrt[3]2', r'\sqrt[3]{2}'),
    (r'\sqrt\alpha', r'\sqrt{\alpha}'),
    (r'\sqrt{\frac12}', r'\sqrt{\frac{1}{2}}'),
    (r'\frac ab', r'\frac{a}{b}'),
    (r'\frac\sqrt2\sqrt3', r'\frac{\sqrt{2}}{\sqrt{3}}'),
    (r'\frac{a+b}{2}', r'\frac{a+b}{2}'),
    (r'\mathbb Q+\hat x', r'\mathbb{Q}+\hat{x}'),
    (r'\mathbb{Q}V\}', r'\mathbb{Q}V\}'),
    (r'\notacommand{x}', r'\notacommand{x}'),
])
def test_tex_atom_grouping_preserves_math_meaning(source, expected):
    assert mathtext_arguments(source) == expected


def test_same_formula_has_same_pixels_for_braced_and_unbraced_tex():
    from PIL import Image
    raw = r'\mathbb{Q}(\sqrt2)=\{a+b\sqrt2\mid a,b\in\mathbb{Q}\}'
    standard = raw.replace(r'\sqrt2', r'\sqrt{2}')
    with Image.open(math_image(raw)) as a, Image.open(math_image(standard)) as b:
        assert a.size == b.size
        assert a.tobytes() == b.tobytes()
    # Do not remove unknown ordinary symbols in an attempt to fix an equation.
    with Image.open(math_image(r'\mathbb{Q}')) as a, Image.open(math_image(r'\mathbb{Q}V')) as b:
        assert a.size != b.size


def test_invalid_formula_is_not_silently_rewritten():
    with pytest.raises(ValueError, match='无法排版公式'):
        math_image(r'\sqrt{2')
    with pytest.raises(ValueError, match='无法排版公式'):
        math_image(r'\notacommand{x}')


def test_pdf_export_accepts_actual_set_formula_in_body_heading_quote_and_table():
    content = r'''## 有理数域扩张 $\mathbb{Q}(\sqrt2)$

集合写作 $\mathbb{Q}(\sqrt2)=\{a+b\sqrt2\mid a,b\in\mathbb{Q}\}$。

$$
\mathbb{Q}(\sqrt2)=\{a+b\sqrt2\mid a,b\in\mathbb{Q}\}
$$

> 原式：$\sqrt2$ 与 $\sqrt[3]2$。

| 项目 | 表达式 |
| --- | --- |
| 商 | $\frac\sqrt2\sqrt3$ |
'''
    path = export_document(content, 'pdf', 'PDF公式兼容性检查', 'formulas.pdf')
    with fitz.open(path) as pdf:
        assert len(pdf) == 1
        assert len(pdf[0].get_images()) >= 5
        assert '集合写作' in pdf[0].get_text()
        assert not any(word in pdf[0].get_text() for word in (r'\sqrt', r'\mathbb'))
        assert pdf[0].get_pixmap().width > 500
