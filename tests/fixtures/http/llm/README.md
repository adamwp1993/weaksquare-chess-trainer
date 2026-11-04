# LLM API responses (fixtures)

Used by the adapter tests in `tests/integration/test_llm_adapters.py` (v0.7).

**Source:** hand-written from the providers' documented shapes (Anthropic's Messages API; OpenAI's
Responses API as typed in the openai-python SDK) until the live test records real ones. Re-record with
`uv run pytest -m live --record-llm` (see docs/DEVELOPER_GUIDE.md). The recorder keeps only the fields
the parsers read (`content`/`output`, `stop_reason`/`status`, `incomplete_details`, `usage`), so no
IDs, headers or keys are stored (SR-12, SR-12a).

Status: anthropic_messages.json recorded from a live response (scrubbed); the other is hand-written.
