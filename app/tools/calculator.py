import ast
import operator
import re
from dataclasses import dataclass
from typing import Callable


class CalculatorError(ValueError):
    """Raised when a calculator expression is invalid or unsafe."""


@dataclass(frozen=True)
class CalculatorResult:
    expression: str
    value: int | float

    @property
    def display_value(self) -> str:
        if isinstance(self.value, float) and self.value.is_integer():
            return str(int(self.value))
        return str(self.value)


_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_FULL_WIDTH_TRANSLATION = str.maketrans(
    {
        "０": "0",
        "１": "1",
        "２": "2",
        "３": "3",
        "４": "4",
        "５": "5",
        "６": "6",
        "７": "7",
        "８": "8",
        "９": "9",
        "＋": "+",
        "－": "-",
        "＊": "*",
        "／": "/",
        "（": "(",
        "）": ")",
        "．": ".",
        "×": "*",
        "÷": "/",
        "％": "%",
        "？": "",
    }
)

_CALCULATION_PREFIXES = (
    "请帮我计算",
    "帮我计算",
    "帮我算一下",
    "请计算",
    "计算一下",
    "算一下",
    "计算",
)

_CALCULATION_SUFFIXES = (
    "等于多少",
    "是多少",
    "结果是多少",
    "的结果",
)


def extract_calculation_expression(text: str) -> str | None:
    candidate = _normalize_expression_text(text)
    for prefix in _CALCULATION_PREFIXES:
        if candidate.startswith(prefix):
            candidate = candidate.removeprefix(prefix)
            break
    for suffix in _CALCULATION_SUFFIXES:
        if candidate.endswith(suffix):
            candidate = candidate.removesuffix(suffix)
            break
    candidate = candidate.strip()
    if not _looks_like_expression(candidate):
        return None
    return candidate.replace("^", "**")


def calculate(expression: str) -> CalculatorResult:
    expression = _normalize_expression_text(expression).replace("^", "**")
    if not _looks_like_expression(expression):
        raise CalculatorError("Only arithmetic expressions are supported.")
    if len(expression) > 120:
        raise CalculatorError("Expression is too long.")
    try:
        tree = ast.parse(expression, mode="eval")
        value = _evaluate_node(tree.body)
    except (ArithmeticError, SyntaxError, RecursionError) as exc:
        raise CalculatorError("Invalid arithmetic expression.") from exc
    if abs(value) > 1_000_000_000:
        raise CalculatorError("Calculation result is too large.")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return CalculatorResult(expression=expression, value=value)


def _normalize_expression_text(text: str) -> str:
    return text.translate(_FULL_WIDTH_TRANSLATION).strip().replace(" ", "")


def _looks_like_expression(text: str) -> bool:
    if not text:
        return False
    if not re.fullmatch(r"[0-9+\-*/().%^]+", text):
        return False
    return bool(re.search(r"\d", text)) and bool(re.search(r"[+\-*/%^]", text))


def _evaluate_node(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value
    if isinstance(node, ast.BinOp):
        operator_type = type(node.op)
        if operator_type not in _BINARY_OPERATORS:
            raise CalculatorError("Unsupported arithmetic operator.")
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise CalculatorError("Exponent is too large.")
        return _BINARY_OPERATORS[operator_type](left, right)
    if isinstance(node, ast.UnaryOp):
        operator_type = type(node.op)
        if operator_type not in _UNARY_OPERATORS:
            raise CalculatorError("Unsupported unary operator.")
        return _UNARY_OPERATORS[operator_type](_evaluate_node(node.operand))
    raise CalculatorError("Unsupported expression.")
