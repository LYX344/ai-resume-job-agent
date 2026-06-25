import pytest

from app.tools.calculator import CalculatorError, calculate, extract_calculation_expression


def test_extract_calculation_expression_from_chinese_query() -> None:
    assert extract_calculation_expression("请计算 2 + 3 * 4 等于多少？") == "2+3*4"


def test_calculate_arithmetic_expression() -> None:
    result = calculate("(2 + 3) * 4 / 2")

    assert result.expression == "(2+3)*4/2"
    assert result.value == 10
    assert result.display_value == "10"


def test_calculate_rejects_unsafe_expression() -> None:
    with pytest.raises(CalculatorError):
        calculate("__import__('os').system('echo unsafe')")


def test_calculate_rejects_division_by_zero() -> None:
    with pytest.raises(CalculatorError):
        calculate("1 / 0")
