from arvectum_data.billing import PriceRule, UsageQuantity, calculate_invoice, normalize_rules


def test_calculate_invoice_applies_included_usage_and_base_fee() -> None:
    result = calculate_invoice(
        base_fee_minor=1000,
        rules=(
            PriceRule(
                operation="search",
                unit="request",
                unit_price_minor=25,
                included_quantity=10,
            ),
            PriceRule(
                operation="research",
                unit="request",
                unit_price_minor=100,
            ),
        ),
        usage=(
            UsageQuantity(operation="search", unit="request", quantity=14),
            UsageQuantity(operation="research", unit="request", quantity=2),
        ),
    )

    assert result.base_fee_minor == 1000
    assert result.subtotal_minor == 1300
    assert result.total_minor == 1300
    assert result.unpriced_usage == ()
    search = next(line for line in result.lines if line.operation == "search")
    assert search.included_quantity == 10
    assert search.chargeable_quantity == 4
    assert search.amount_minor == 100


def test_calculate_invoice_surfaces_unpriced_usage() -> None:
    result = calculate_invoice(
        base_fee_minor=0,
        rules=(PriceRule(operation="search", unit="request", unit_price_minor=1),),
        usage=(UsageQuantity(operation="answer", unit="request", quantity=3),),
    )

    assert result.total_minor == 0
    assert result.unpriced_usage == (
        UsageQuantity(operation="answer", unit="request", quantity=3),
    )


def test_normalize_rules_rejects_duplicate_meter() -> None:
    try:
        normalize_rules(
            (
                {"operation": "search", "unit": "request", "unit_price_minor": 1},
                {"operation": "search", "unit": "request", "unit_price_minor": 2},
            )
        )
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate billing rule should fail")
