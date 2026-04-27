"""
Medical triage — symptom severity classification.

Classifies a patient-reported symptom description into a severity tier
and recommended next-step category. This is a demonstration of how
llm-salvage parses structured output for high-stakes domains, NOT an
endorsement of using LLMs for medical decision-making.

Real triage systems require clinical validation, regulatory compliance
(HIPAA, FDA, etc.), human review, and integration with real patient
records. This example illustrates the parsing layer only.

Note the use of strict ``critical_codes`` — in a high-stakes domain,
any ambiguity in the structured output should fail the parse rather
than be silently accepted with a "best guess" correction.

Run::

    python examples/medical_triage.py
"""
from __future__ import annotations

from llm_salvage import Field, ResponseParser, Schema


SCHEMA = Schema(
    fields={
        "severity":     Field(choices=["emergency", "urgent", "routine", "self_care"]),
        "category":     Field(choices=[
            "respiratory", "cardiac", "gastrointestinal", "musculoskeletal",
            "neurological", "dermatological", "psychiatric", "other",
        ]),
        "next_step":    Field(choices=[
            "call_911", "go_to_er", "schedule_urgent_visit",
            "schedule_routine_visit", "self_care_with_monitoring",
        ]),
        "rationale":    Field(min_length=50, max_length=600),
        "red_flags":    Field(required=False),
        "requires_human_review": Field(
            choices=["yes", "no"],
            required=False,
            default="yes",  # safer default than "no"
        ),
    },
    # In medical contexts, anything short of a clean structured output
    # should be reviewed manually. Promote everything that hints at
    # parsing trouble to critical.
    critical_codes=frozenset({
        "missing_required",
        "invalid_choice",
        "unfilled_template",
        "no_content",
        "too_short",
        "probability_sum",
        "invalid_integer",
        "invalid_float",
    }),
)


EXAMPLE_RESPONSES = [
    # High-severity case — chest pain pattern.
    """
[SEVERITY] emergency [/SEVERITY]
[CATEGORY] cardiac [/CATEGORY]
[NEXT_STEP] call_911 [/NEXT_STEP]
[RATIONALE]
Patient reports sudden onset crushing chest pain radiating to left arm
with associated diaphoresis and shortness of breath. This presentation
matches classic acute coronary syndrome warning signs and warrants
immediate emergency evaluation rather than scheduled care.
[/RATIONALE]
[RED_FLAGS] crushing chest pain, radiation to left arm, diaphoresis [/RED_FLAGS]
[REQUIRES_HUMAN_REVIEW] yes [/REQUIRES_HUMAN_REVIEW]
""",

    # Routine case — minor strain.
    """
{
  "severity": "self_care",
  "category": "musculoskeletal",
  "next_step": "self_care_with_monitoring",
  "rationale": "Patient describes a mild ankle twist while walking yesterday. Pain is 3/10, can bear weight, no visible swelling or bruising, no inability to use the joint. Conservative management appropriate with re-evaluation if symptoms worsen.",
  "requires_human_review": "no"
}
""",

    # Schedule visit case — persistent but not acute.
    """
[SEVERITY] routine [/SEVERITY]
[CATEGORY] dermatological [/CATEGORY]
[NEXT_STEP] schedule_routine_visit [/NEXT_STEP]
[RATIONALE]
Patient reports a slowly enlarging mole over the past three months
with mild irregular borders. No bleeding or significant color change.
Warrants dermatology evaluation but not urgent — typical wait times
for routine appointments are appropriate given the gradual progression.
[/RATIONALE]
[RED_FLAGS] enlarging size, irregular borders [/RED_FLAGS]
""",
]


def main() -> None:
    parser = ResponseParser(SCHEMA, model="example")

    for i, response in enumerate(EXAMPLE_RESPONSES, start=1):
        result = parser.parse(response)

        print(f"--- Case {i} ---")
        if result.ok:
            print(f"  severity:   {result.data['severity']}")
            print(f"  category:   {result.data['category']}")
            print(f"  next_step:  {result.data['next_step']}")
            print(f"  human_review: {result.data['requires_human_review']}")
            if "red_flags" in result.data:
                print(f"  red_flags:  {result.data['red_flags']}")
            print(f"  rationale:  {result.data['rationale'][:100]}...")
        else:
            print("  parse failed (output not safe to act on, requires human review):")
            for err in result.errors:
                print(f"    {err}")

        if result.corrections:
            print(f"  corrections: {result.corrections}")
        print()

    print("=" * 60)
    print("Reminder: this is a parsing demonstration, not a medical")
    print("triage system. Real clinical decisions require human")
    print("review and appropriate regulatory compliance.")


if __name__ == "__main__":
    main()
