"""
Product extraction — structured attributes from descriptions.

Pulls product specs (category, brand, price, key features, condition)
from free-form product descriptions written by sellers. Demonstrates
mixed field types (CHOICE, STRING, FLOAT, INTEGER) and handling of
optional fields with defaults.

Run::

    python examples/product_extraction.py
"""
from __future__ import annotations

from llm_salvage import Field, FieldType, ResponseParser, Schema


SCHEMA = Schema(fields={
    "category":    Field(choices=[
        "electronics", "clothing", "home", "books", "toys", "other",
    ]),
    "brand":       Field(min_length=1, max_length=80),
    "price_usd":   Field(type=FieldType.FLOAT),
    "condition":   Field(choices=["new", "like_new", "good", "fair", "poor"]),
    "model_year":  Field(type=FieldType.INTEGER, required=False),
    "key_features": Field(min_length=10, max_length=500),
    "in_stock":    Field(choices=["yes", "no"], required=False, default="yes"),
})


EXAMPLE_RESPONSES = [
    # Tagged format with all fields populated.
    """
[CATEGORY] electronics [/CATEGORY]
[BRAND] Sony [/BRAND]
[PRICE_USD] 349.99 [/PRICE_USD]
[CONDITION] new [/CONDITION]
[MODEL_YEAR] 2024 [/MODEL_YEAR]
[KEY_FEATURES]
Wireless noise-cancelling over-ear headphones with 30-hour battery life,
Bluetooth 5.3, USB-C charging, and adaptive sound control.
[/KEY_FEATURES]
[IN_STOCK] yes [/IN_STOCK]
""",

    # JSON format, model_year omitted (optional field, no default — should be absent).
    """
{
  "category": "clothing",
  "brand": "Patagonia",
  "price_usd": 159.00,
  "condition": "like_new",
  "key_features": "Men's down jacket, size large, 800-fill recycled down, water-resistant outer shell. Worn twice, still has original tags."
}
""",

    # JSON with price as string (LLM mistake — model formatted as currency).
    # Float coercion handles this gracefully.
    """
```json
{
  "category": "home",
  "brand": "KitchenAid",
  "price_usd": "249.50",
  "condition": "good",
  "model_year": 2019,
  "key_features": "Stand mixer, 5-quart bowl, 10 speeds. Some cosmetic scratches on the housing but mechanically sound. Includes original whisk and dough hook attachments."
}
```
""",
]


def main() -> None:
    parser = ResponseParser(SCHEMA, model="example")

    for i, response in enumerate(EXAMPLE_RESPONSES, start=1):
        result = parser.parse(response)

        print(f"--- Product {i} ---")
        if result.ok:
            print(f"  category:     {result.data['category']}")
            print(f"  brand:        {result.data['brand']}")
            print(f"  price_usd:    ${result.data['price_usd']:.2f}")
            print(f"  condition:    {result.data['condition']}")
            if "model_year" in result.data:
                print(f"  model_year:   {result.data['model_year']}")
            print(f"  in_stock:     {result.data.get('in_stock', 'unknown')}")
            print(f"  key_features: {result.data['key_features'][:80]}...")
        else:
            print("  parse failed:")
            for err in result.errors:
                print(f"    {err}")

        if result.corrections:
            print(f"  corrections: {result.corrections}")
        print()


if __name__ == "__main__":
    main()
