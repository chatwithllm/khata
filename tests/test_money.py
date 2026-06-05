import pytest

from khata.money import to_minor, format_minor


def test_to_minor_parses_decimal_and_grouping():
    assert to_minor("12,40,000", "INR") == 124000000
    assert to_minor("12.50", "USD") == 1250
    assert to_minor(1500, "INR") == 150000


def test_to_minor_rounds_half_up():
    assert to_minor("0.015", "USD") == 2  # 1.5 cents → 2


def test_to_minor_rejects_unknown_currency_and_empty():
    with pytest.raises(ValueError):
        to_minor("10", "EUR")
    with pytest.raises(ValueError):
        to_minor("", "INR")


def test_format_minor_groups_with_two_decimals():
    assert format_minor(124000000, "INR") == "1,240,000.00"
    assert format_minor(-1250, "USD") == "-12.50"


def test_to_minor_rejects_float_and_nonfinite():
    with pytest.raises(TypeError):
        to_minor(12.5, "INR")
    with pytest.raises(ValueError):
        to_minor("NaN", "USD")


def test_to_minor_zero_and_negative():
    assert to_minor("0", "INR") == 0
    assert to_minor("-50.25", "INR") == -5025


def test_format_minor_rejects_unknown_currency():
    with pytest.raises(ValueError):
        format_minor(0, "EUR")


def test_pct_to_bps_and_format():
    from khata.money import pct_to_bps, format_bps
    assert pct_to_bps("8.5") == 850
    assert pct_to_bps("2") == 200
    assert pct_to_bps("8.5%") == 850
    assert format_bps(850) == "8.5"
    assert format_bps(200) == "2"
    assert format_bps(0) == "0"


def test_pct_to_bps_rejects_float_and_empty():
    from khata.money import pct_to_bps
    with pytest.raises(TypeError):
        pct_to_bps(8.5)
    with pytest.raises(ValueError):
        pct_to_bps("")


def test_to_micro_round_trip():
    from khata.money import to_micro, format_micro
    assert to_micro("92.5") == 92_500_000
    assert to_micro(10) == 10_000_000
    assert to_micro("1,250.125") == 1_250_125_000
    assert format_micro(92_500_000) == "92.5"
    assert format_micro(10_000_000) == "10"
    assert format_micro(1_250_125_000) == "1250.125"


def test_to_micro_rejects_float():
    import pytest
    from khata.money import to_micro
    with pytest.raises(TypeError):
        to_micro(92.5)


def test_to_micro_rejects_garbage():
    import pytest
    from khata.money import to_micro
    with pytest.raises(ValueError):
        to_micro("")
    with pytest.raises(Exception):
        to_micro("abc")


def test_to_minor_rejects_garbage_with_valueerror():
    import pytest
    from khata.money import to_minor, to_micro, pct_to_bps
    with pytest.raises(ValueError):
        to_minor("abc", "INR")
    with pytest.raises(ValueError):
        to_micro("abc")
    with pytest.raises(ValueError):
        pct_to_bps("abc")
    # valid input still parses
    assert to_minor("12.50", "INR") == 1250
    assert to_micro("3.5") == 3500000
    assert pct_to_bps("8.5") == 850
