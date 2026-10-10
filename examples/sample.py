"""
Sample Python module for testing the AI Test Case Generator.
Run this to verify the engine works:

    python engine/main.py --file examples/sample.py --api-key YOUR_KEY
"""


def calculate_discount(price: float, discount_percent: float) -> float:
    """
    Calculate the discounted price.

    Args:
        price: Original price (must be >= 0)
        discount_percent: Discount percentage (0-100)

    Returns:
        The price after discount.

    Raises:
        ValueError: If price is negative or discount is out of range.
    """
    if price < 0:
        raise ValueError("Price cannot be negative")
    if not (0 <= discount_percent <= 100):
        raise ValueError("Discount must be between 0 and 100")

    return round(price * (1 - discount_percent / 100), 2)


def fizzbuzz(n: int) -> str:
    """Return 'Fizz', 'Buzz', 'FizzBuzz', or the number as string."""
    if n % 15 == 0:
        return "FizzBuzz"
    if n % 3 == 0:
        return "Fizz"
    if n % 5 == 0:
        return "Buzz"
    return str(n)


def flatten(nested_list: list) -> list:
    """Flatten a nested list of arbitrary depth."""
    result = []
    for item in nested_list:
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result


class TemperatureConverter:
    """Converts between Celsius, Fahrenheit, and Kelvin."""

    def celsius_to_fahrenheit(self, celsius: float) -> float:
        """Convert Celsius to Fahrenheit."""
        return round(celsius * 9 / 5 + 32, 2)

    def fahrenheit_to_celsius(self, fahrenheit: float) -> float:
        """Convert Fahrenheit to Celsius."""
        return round((fahrenheit - 32) * 5 / 9, 2)

    def celsius_to_kelvin(self, celsius: float) -> float:
        """Convert Celsius to Kelvin. Raises ValueError if below absolute zero."""
        if celsius < -273.15:
            raise ValueError("Temperature below absolute zero")
        return round(celsius + 273.15, 2)
