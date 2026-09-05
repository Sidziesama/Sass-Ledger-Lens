from .models import BenchmarkCase, BenchmarkScore, CaseScore, ExpectedAccountResult


def load_cases(*args, **kwargs):
    from .benchmark import load_cases as implementation

    return implementation(*args, **kwargs)


def evaluate_case(*args, **kwargs):
    from .benchmark import evaluate_case as implementation

    return implementation(*args, **kwargs)


def run_benchmark(*args, **kwargs):
    from .benchmark import run_benchmark as implementation

    return implementation(*args, **kwargs)


__all__ = [
    "BenchmarkCase",
    "BenchmarkScore",
    "CaseScore",
    "ExpectedAccountResult",
    "evaluate_case",
    "load_cases",
    "run_benchmark",
]
