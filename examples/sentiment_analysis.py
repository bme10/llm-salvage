"""
Sentiment analysis — review classification.

Classifies product reviews into positive/negative/neutral with a confidence
level and a one-line summary. This is the canonical intro example: small
schema, clear field types, demonstrates the basic pipeline end to end.

Run::

    python examples/sentiment_analysis.py
"""
from __future__ import annotations

from llm_salvage import Field, ResponseParser, Schema


SCHEMA = Schema(fields={
    "sentiment":  Field(choices=["positive", "negative", "neutral"]),
    "confidence": Field(choices=["high", "medium", "low"]),
    "summary":    Field(min_length=20, max_length=200),
    "key_phrase": Field(required=False),
})


# A handful of model responses you might see across providers and prompts.
# Each demonstrates a different real-world quirk the parser handles.
EXAMPLE_RESPONSES = [
    # Tagged format, perfectly clean.
    """
[SENTIMENT] positive [/SENTIMENT]
[CONFIDENCE] high [/CONFIDENCE]
[SUMMARY]
The customer praised the build quality and ease of setup, mentioning
they would recommend to friends.
[/SUMMARY]
[KEY_PHRASE] would recommend to friends [/KEY_PHRASE]
""",

    # JSON wrapped in code fences with a trailing comma — common from
    # local models that learned JSON output from training data with fences.
    """
```json
{
  "sentiment": "Negative",
  "confidence": "MEDIUM",
  "summary": "Customer reported a defective unit and a frustrating return process that took over two weeks.",
}
```
""",

    # Mixed case, tagged format, with the model adding a preamble it
    # was instructed not to.
    """
Here's my analysis of the review:

[SENTIMENT] Neutral [/SENTIMENT]
[CONFIDENCE] Low [/CONFIDENCE]
[SUMMARY]
The review describes both a working product and a slow shipping
experience, with no clear overall verdict from the customer.
[/SUMMARY]
""",
]


def main() -> None:
    parser = ResponseParser(SCHEMA, model="example")

    for i, response in enumerate(EXAMPLE_RESPONSES, start=1):
        result = parser.parse(response)

        print(f"--- Response {i} ---")
        if result.ok:
            print(f"  sentiment:  {result.data['sentiment']}")
            print(f"  confidence: {result.data['confidence']}")
            print(f"  summary:    {result.data['summary'][:80]}...")
            if "key_phrase" in result.data:
                print(f"  key_phrase: {result.data['key_phrase']}")
        else:
            print("  parse failed:")
            for err in result.errors:
                print(f"    {err}")

        if result.corrections:
            print(f"  corrections applied: {result.corrections}")
        print()


if __name__ == "__main__":
    main()
