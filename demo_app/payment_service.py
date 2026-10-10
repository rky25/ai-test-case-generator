"""
Payment and tax calculation service for the e-commerce system.
Imports domain models from models.py to test cross-file dependency resolution.
"""

from typing import Dict
from models import Order, OrderItem


TAX_RATES: Dict[str, float] = {
    "CA": 0.0725,
    "NY": 0.08875,
    "TX": 0.0625,
    "FL": 0.060,
    "WA": 0.065,
}

COUPON_CODES: Dict[str, float] = {
    "WELCOME10": 0.10,
    "SUMMER20": 0.20,
    "HALFPRICE": 0.50,
}


def calculate_sales_tax(subtotal: float, state_code: str) -> float:
    """
    Calculate sales tax based on state code.

    Args:
        subtotal: Order subtotal before tax (must be >= 0).
        state_code: 2-letter US state code.

    Returns:
        Tax amount rounded to 2 decimal places.

    Raises:
        ValueError: If subtotal is negative or state code is unknown.
    """
    if subtotal < 0:
        raise ValueError("Subtotal cannot be negative")

    code = state_code.strip().upper()
    if code not in TAX_RATES:
        raise ValueError(f"Unknown or unsupported state: {state_code}")

    rate = TAX_RATES[code]
    return round(subtotal * rate, 2)


def apply_discount_coupon(subtotal: float, coupon_code: str) -> float:
    """
    Apply a promotional coupon code to calculate discount amount.

    Args:
        subtotal: Order subtotal.
        coupon_code: Coupon string.

    Returns:
        Discount amount (float).

    Raises:
        ValueError: If subtotal is non-positive or coupon is invalid.
    """
    if subtotal <= 0:
        raise ValueError("Subtotal must be greater than zero to apply discount")

    code = coupon_code.strip().upper()
    if code not in COUPON_CODES:
        raise ValueError(f"Invalid or expired coupon code: {coupon_code}")

    discount_ratio = COUPON_CODES[code]
    return round(subtotal * discount_ratio, 2)


def process_order_checkout(order: Order, state_code: str, coupon_code: str = "") -> dict:
    """
    Process order checkout by applying coupons, calculating taxes, and finalizing total.

    Args:
        order: Order dataclass instance from models.py.
        state_code: Shipping state code for tax calculation.
        coupon_code: Optional discount coupon code.

    Returns:
        Dict summarizing payment receipt.

    Raises:
        ValueError: If order has no items or order total cannot be processed.
    """
    if not order.items:
        raise ValueError("Cannot checkout an empty order")

    items_subtotal = sum(item.subtotal for item in order.items)

    discount = 0.0
    if coupon_code:
        discount = apply_discount_coupon(items_subtotal, coupon_code)

    taxable_amount = max(0.0, items_subtotal - discount)
    tax = calculate_sales_tax(taxable_amount, state_code)

    order.discount_amount = discount
    order.tax_amount = tax
    order.status = "paid"

    return {
        "order_id": order.id,
        "user_id": order.user_id,
        "items_count": len(order.items),
        "subtotal": round(items_subtotal, 2),
        "discount": discount,
        "tax": tax,
        "final_total": order.total,
        "status": order.status,
    }
