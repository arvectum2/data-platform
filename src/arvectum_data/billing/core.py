from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class PriceRule:
    operation: str
    unit: str
    unit_price_minor: int
    included_quantity: int = 0
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.operation.strip():
            raise ValueError("billing operation must not be blank")
        if not self.unit.strip():
            raise ValueError("billing unit must not be blank")
        if self.unit_price_minor < 0:
            raise ValueError("unit_price_minor must be non-negative")
        if self.included_quantity < 0:
            raise ValueError("included_quantity must be non-negative")


@dataclass(frozen=True, slots=True)
class UsageQuantity:
    operation: str
    unit: str
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity < 0:
            raise ValueError("usage quantity must be non-negative")


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    operation: str
    unit: str
    quantity: int
    included_quantity: int
    chargeable_quantity: int
    unit_price_minor: int
    amount_minor: int
    description: str | None = None


@dataclass(frozen=True, slots=True)
class InvoiceCalculation:
    base_fee_minor: int
    subtotal_minor: int
    total_minor: int
    lines: tuple[InvoiceLine, ...]
    unpriced_usage: tuple[UsageQuantity, ...]


def normalize_rules(raw_rules: Iterable[Mapping[str, object]]) -> tuple[PriceRule, ...]:
    result: list[PriceRule] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_rules:
        rule = PriceRule(
            operation=str(raw.get("operation") or "").strip(),
            unit=str(raw.get("unit") or "").strip(),
            unit_price_minor=int(raw.get("unit_price_minor") or 0),
            included_quantity=int(raw.get("included_quantity") or 0),
            description=(
                str(raw["description"]).strip()
                if raw.get("description") is not None
                else None
            ),
        )
        identity = (rule.operation, rule.unit)
        if identity in seen:
            raise ValueError(
                f"duplicate billing price rule for {rule.operation}/{rule.unit}"
            )
        seen.add(identity)
        result.append(rule)
    if not result:
        raise ValueError("at least one billing price rule is required")
    return tuple(result)


def calculate_invoice(
    *,
    base_fee_minor: int,
    rules: Iterable[PriceRule],
    usage: Iterable[UsageQuantity],
) -> InvoiceCalculation:
    if base_fee_minor < 0:
        raise ValueError("base_fee_minor must be non-negative")

    rule_map = {(rule.operation, rule.unit): rule for rule in rules}
    usage_map: dict[tuple[str, str], int] = {}
    for item in usage:
        key = (item.operation, item.unit)
        usage_map[key] = usage_map.get(key, 0) + item.quantity

    lines: list[InvoiceLine] = []
    unpriced: list[UsageQuantity] = []
    subtotal = int(base_fee_minor)

    for key in sorted(usage_map):
        quantity = usage_map[key]
        operation, unit = key
        rule = rule_map.get(key)
        if rule is None:
            if quantity:
                unpriced.append(
                    UsageQuantity(
                        operation=operation,
                        unit=unit,
                        quantity=quantity,
                    )
                )
            continue
        included = min(quantity, rule.included_quantity)
        chargeable = max(0, quantity - rule.included_quantity)
        amount = chargeable * rule.unit_price_minor
        subtotal += amount
        lines.append(
            InvoiceLine(
                operation=operation,
                unit=unit,
                quantity=quantity,
                included_quantity=included,
                chargeable_quantity=chargeable,
                unit_price_minor=rule.unit_price_minor,
                amount_minor=amount,
                description=rule.description,
            )
        )

    return InvoiceCalculation(
        base_fee_minor=int(base_fee_minor),
        subtotal_minor=subtotal,
        total_minor=subtotal,
        lines=tuple(lines),
        unpriced_usage=tuple(unpriced),
    )
