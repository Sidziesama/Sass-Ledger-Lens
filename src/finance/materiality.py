"""Rules for ranking financially material changes."""

from dataclasses import dataclass
from decimal import Decimal

from .variance import AccountVariance


@dataclass(frozen=True)
class MaterialVariance:
    result: AccountVariance
    is_material: bool
    materiality_score: Decimal


def rank_material_variances(
    variances: list[AccountVariance],
    absolute_threshold: Decimal = Decimal("0"),
    percentage_threshold: Decimal = Decimal("0"),
) -> list[MaterialVariance]:
    ranked = []
    for result in variances:
        abs_change = abs(result.variance)
        pct_change = abs(result.variance_pct or Decimal("0"))
        is_material = abs_change >= absolute_threshold and pct_change >= percentage_threshold
        ranked.append(MaterialVariance(result, is_material, abs_change))
    return sorted(ranked, key=lambda item: (-item.materiality_score, item.result.account))
