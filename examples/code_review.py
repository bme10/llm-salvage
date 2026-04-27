"""
Code review — extracting findings from LLM code review output.

Captures the verdict, severity counts, and a structured summary from a
code review response. Demonstrates ``Schema.from_file()`` — the schema
lives in a YAML file alongside the code, which is useful when the same
schema is shared across multiple consumers.

Run::

    python examples/code_review.py

Requires::

    pip install 'llm-salvage[yaml]'
"""
from __future__ import annotations

from pathlib import Path

from llm_salvage import ResponseParser, Schema


# In a real project this YAML lives in a config directory or a shared
# repo. For this example we generate it on the fly so the script is
# self-contained.
SCHEMA_YAML = """
fields:
  verdict:
    choices: [approve, request_changes, comment_only]
  severity:
    choices: [critical, major, minor, none]
  num_issues:
    type: integer
    required: false
    default: 0
  summary:
    min_length: 30
    max_length: 600
  primary_concern:
    required: false
  blocking:
    # Quote 'yes'/'no' explicitly — YAML 1.1 parsers auto-convert bare
    # yes/no/true/false/on/off to booleans, which would break the
    # choices list. This is a YAML pitfall, not an llm-salvage one.
    choices: ["yes", "no"]
    required: false
    default: "no"

formats: [tagged, json]

# The code review tool we're parsing happens to use these alternate keys.
key_aliases:
  decision: verdict
  highest_severity: severity
  issue_count: num_issues
  review_summary: summary
  main_issue: primary_concern
  blocks_merge: blocking
"""


EXAMPLE_RESPONSES = [
    # Tagged format, request_changes verdict.
    """
[VERDICT] request_changes [/VERDICT]
[SEVERITY] major [/SEVERITY]
[NUM_ISSUES] 3 [/NUM_ISSUES]
[SUMMARY]
The implementation introduces a SQL injection vulnerability in the user
search endpoint, lacks input validation on file uploads, and has two
unhandled exception paths that will crash the worker on malformed input.
Tests are missing for the new endpoints.
[/SUMMARY]
[PRIMARY_CONCERN] SQL injection in search endpoint [/PRIMARY_CONCERN]
[BLOCKING] yes [/BLOCKING]
""",

    # JSON with non-canonical key names — caught by aliases.
    """
{
  "decision": "approve",
  "highest_severity": "minor",
  "issue_count": 1,
  "review_summary": "Implementation is correct and well-tested. One minor suggestion to extract the retry logic into a helper, but not blocking. Documentation updated appropriately.",
  "main_issue": "Retry logic could be extracted for reuse",
  "blocks_merge": "no"
}
""",

    # Comment-only, no issues, optional fields omitted.
    """
[VERDICT] comment_only [/VERDICT]
[SEVERITY] none [/SEVERITY]
[SUMMARY]
The change is purely cosmetic — variable renames and comment updates.
No functional changes to review. Approved without further checks.
[/SUMMARY]
""",
]


def main() -> None:
    # Write the YAML schema to a temp file and load it. Using
    # tempfile.gettempdir() ensures this works on Windows, macOS, and
    # Linux without hardcoding a path.
    import tempfile
    schema_path = Path(tempfile.gettempdir()) / "code_review_schema.yaml"
    schema_path.write_text(SCHEMA_YAML, encoding="utf-8")

    schema = Schema.from_file(schema_path)
    parser = ResponseParser(schema, model="example")

    for i, response in enumerate(EXAMPLE_RESPONSES, start=1):
        result = parser.parse(response)

        print(f"--- Review {i} ---")
        if result.ok:
            print(f"  verdict:      {result.data['verdict']}")
            print(f"  severity:     {result.data['severity']}")
            print(f"  num_issues:   {result.data['num_issues']}")
            print(f"  blocking:     {result.data['blocking']}")
            if "primary_concern" in result.data:
                print(f"  concern:      {result.data['primary_concern']}")
            print(f"  summary:      {result.data['summary'][:80]}...")
        else:
            print("  parse failed:")
            for err in result.errors:
                print(f"    {err}")

        if result.corrections:
            print(f"  corrections: {result.corrections}")
        print()


if __name__ == "__main__":
    main()
