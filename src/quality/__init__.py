"""Deterministic data-quality and reliability checks."""

from .gate import QualityFlag, QualityReport, run_quality_gate

__all__ = ["QualityFlag", "QualityReport", "run_quality_gate"]
