from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


class CurrencyConversionService:
    _RATES_TO_EUR = {
        "USD": Decimal("0.92"),
        "DKK": Decimal("0.134"),
    }

    def __init__(self, base_currency: str = "EUR") -> None:
        self._base_currency = base_currency
        if self._base_currency != "EUR":
            raise ValueError(f"Unsupported base currency: {self._base_currency}")

    def convert(self, amount: Decimal, from_currency: str) -> Decimal:
        if from_currency == self._base_currency:
            return self._quantize(amount)

        rate = self._RATES_TO_EUR.get(from_currency)
        if rate is None:
            raise ValueError(
                f"Unsupported currency conversion: {from_currency} -> {self._base_currency}"
            )

        return self._quantize(amount * rate)

    @staticmethod
    def _quantize(amount: Decimal) -> Decimal:
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
