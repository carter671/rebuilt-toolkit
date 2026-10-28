"""As-built PDF extraction helpers (the real property PDFs are private and not in the repo)."""
import pytest

from rebuilt.capture.asbuilt import decode_code, fmt_in, parse_dim


@pytest.mark.parametrize("raw,inches", [("8'-3  15 16 \"", 99.9375), ("39'-8  1 2 \"", 476.5), ("5  3 8 \"", 5.375),
                                        ("11'-6\"", 138), ("4'", 48), ("6\"", 6), ("32'", 384)])
def test_parse_dim(raw, inches):
    assert parse_dim(raw) == pytest.approx(inches)


@pytest.mark.parametrize("code,reading", [("2459", (2, 4, 5, 9)), ("24510", (2, 4, 5, 10)), ("28010", (2, 8, 0, 10)),
                                          ("110511", (1, 10, 5, 11)), ("9080", (9, 0, 8, 0)), ("51171", (5, 11, 7, 1))])
def test_decode_code_unique(code, reading):
    assert decode_code(code) == [reading]


def test_fmt_in():
    assert fmt_in(99.9375) == "8'-3 15/16\""
