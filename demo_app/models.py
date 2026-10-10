"""
Domain models for the demo enterprise e-commerce system.
Used to demonstrate cross-file dependency resolution in AI Test Case Generator.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class User:
    id: int
    email: str
    role: str = "customer"
    is_active: bool = True


@dataclass
class Product:
    id: int
    name: str
    price: float
    stock: int


@dataclass
class OrderItem:
    product_id: int
    quantity: int
    unit_price: float

    @property
    def subtotal(self) -> float:
        return round(self.quantity * self.unit_price, 2)


@dataclass
class Order:
    id: int
    user_id: int
    items: List[OrderItem] = field(default_factory=list)
    discount_amount: float = 0.0
    tax_amount: float = 0.0
    status: str = "pending"

    @property
    def total(self) -> float:
        items_total = sum(item.subtotal for item in self.items)
        return max(0.0, round(items_total - self.discount_amount + self.tax_amount, 2))
