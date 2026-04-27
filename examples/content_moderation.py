"""
Content moderation — flag classification.

Determines whether a piece of user-generated content should be flagged,
and if so the reason category, severity, and recommended action.
Demonstrates ``critical_codes`` override — a moderation pipeline cannot
tolerate ambiguous outputs the way a sentiment analyzer can, so we
promote ``too_short`` and ``probability_sum`` to critical.

Run::

    python examples/content_moderation.py
"""
from __future__ import annotations

from llm_salvage import Field, FieldType, ResponseParser, Schema


SCHEMA = Schema(
    fields={
        "flagged":      Field(choices=["yes", "no"]),
        "category":     Field(choices=[
            "spam", "harassment", "hate_speech", "violence", "self_harm",
            "sexual", "illegal", "misinformation", "off_topic", "none",
        ]),
        "severity":     Field(choices=["high", "medium", "low", "none"]),
        "action":       Field(choices=["remove", "review", "warn", "allow"]),
        "rationale":    Field(min_length=30, max_length=400),
        "confidence":   Field(type=FieldType.PROBABILITY, required=False),
    },
    # Moderation outputs that fall short on length or have malformed
    # probability distributions are not safe to act on. Promote those to
    # critical so result.ok is False when they occur.
    critical_codes=frozenset({
        "missing_required",
        "invalid_choice",
        "unfilled_template",
        "no_content",
        "too_short",
        "probability_sum",
    }),
)


EXAMPLE_RESPONSES = [
    # Tagged format with a probability distribution.
    """
[FLAGGED] yes [/FLAGGED]
[CATEGORY] harassment [/CATEGORY]
[SEVERITY] high [/SEVERITY]
[ACTION] remove [/ACTION]
[RATIONALE]
The post contains direct threats and personal attacks targeting another
user by name, with explicit calls for others to participate in the
harassment campaign.
[/RATIONALE]
[CONFIDENCE] flagged=92 borderline=6 clean=2 [/CONFIDENCE]
""",

    # Clean content — no flag.
    """
[FLAGGED] no [/FLAGGED]
[CATEGORY] none [/CATEGORY]
[SEVERITY] none [/SEVERITY]
[ACTION] allow [/ACTION]
[RATIONALE]
The post is a benign comment about weekend plans with no policy
violations identified across any moderation category.
[/RATIONALE]
""",

    # JSON format, ambiguous case. Probability is encoded as a string here
    # rather than a nested dict — the parser's nested-dict probability
    # extraction is currently limited; see docs/limitations.md.
    """
{
  "flagged": "yes",
  "category": "spam",
  "severity": "low",
  "action": "review",
  "rationale": "The post contains promotional links to an external site, but the context suggests legitimate community recommendation rather than commercial spam.",
  "confidence": "flagged=55 borderline=35 clean=10"
}
""",
]


def main() -> None:
    parser = ResponseParser(SCHEMA, model="example")

    for i, response in enumerate(EXAMPLE_RESPONSES, start=1):
        result = parser.parse(response)

        print(f"--- Item {i} ---")
        if result.ok:
            print(f"  flagged:   {result.data['flagged']}")
            print(f"  category:  {result.data['category']}")
            print(f"  severity:  {result.data['severity']}")
            print(f"  action:    {result.data['action']}")
            print(f"  rationale: {result.data['rationale'][:100]}...")
            if "confidence" in result.data:
                print(f"  confidence: {result.data['confidence']}")
        else:
            print("  parse failed (output not safe to act on):")
            for err in result.errors:
                print(f"    {err}")

        if result.corrections:
            print(f"  corrections: {result.corrections}")
        print()


if __name__ == "__main__":
    main()
