"""
Support triage — customer ticket routing.

Classifies inbound support tickets by topic, urgency, and suggested
team owner, plus a summary used by the routing UI. Demonstrates
``key_aliases`` for adapting LLM output that uses different field
names than the canonical schema.

Run::

    python examples/support_triage.py
"""
from __future__ import annotations

from llm_salvage import Field, ResponseParser, Schema


SCHEMA = Schema(
    fields={
        "topic":           Field(choices=["billing", "technical", "account", "general"]),
        "priority":        Field(choices=["urgent", "normal", "low"]),
        "suggested_owner": Field(choices=["billing_team", "engineering", "support_l1", "support_l2"]),
        "summary":         Field(min_length=10, max_length=300),
        "needs_callback":  Field(choices=["yes", "no"], required=False, default="no"),
    },
    # LLMs sometimes pick different but reasonable field names than your
    # schema. Aliases let you accept those without rewriting prompts.
    key_aliases={
        "category":      "topic",
        "urgency_level": "priority",
        "team":           "suggested_owner",
        "description":    "summary",
    },
)


EXAMPLE_RESPONSES = [
    # JSON with non-canonical key names — caught by aliases.
    """
{
  "ticket_classification": {
    "category": "billing",
    "urgency_level": "urgent",
    "team": "billing_team",
    "description": "Customer reports being charged twice for the annual subscription renewal."
  }
}
""",

    # Tagged format, canonical names, with the optional needs_callback field.
    """
[TOPIC] technical [/TOPIC]
[PRIORITY] normal [/PRIORITY]
[SUGGESTED_OWNER] engineering [/SUGGESTED_OWNER]
[SUMMARY]
User cannot enable two-factor authentication. Settings page returns
a 500 error after entering the verification code.
[/SUMMARY]
[NEEDS_CALLBACK] yes [/NEEDS_CALLBACK]
""",

    # JSON, missing the optional field — schema default fills it in.
    """
```json
{
  "topic": "general",
  "priority": "low",
  "suggested_owner": "support_l1",
  "summary": "User asking about discount eligibility for non-profit organizations."
}
```
""",
]


def main() -> None:
    parser = ResponseParser(SCHEMA, model="example")

    for i, response in enumerate(EXAMPLE_RESPONSES, start=1):
        result = parser.parse(response)

        print(f"--- Ticket {i} ---")
        if result.ok:
            print(f"  topic:           {result.data['topic']}")
            print(f"  priority:        {result.data['priority']}")
            print(f"  suggested_owner: {result.data['suggested_owner']}")
            print(f"  summary:         {result.data['summary']}")
            print(f"  needs_callback:  {result.data['needs_callback']}")
        else:
            print("  parse failed:")
            for err in result.errors:
                print(f"    {err}")

        if result.corrections:
            print(f"  corrections: {result.corrections}")
        print()


if __name__ == "__main__":
    main()
