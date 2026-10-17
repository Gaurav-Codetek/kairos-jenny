"""What a tool call costs the calling agent: tokens and estimated price."""

from kairos_kb.context.usage import as_agent_sees, call_usage, count_tokens


def test_tokens_are_counted_with_the_gpt5_tokenizer():
    assert count_tokens("") == 0
    assert 3 <= count_tokens("column order mismatch") <= 5


def test_responses_are_priced_as_input_and_arguments_as_output():
    usage = call_usage({"question": "account sales"}, {"results": ["x" * 40]})
    assert usage["args_tokens"] > 0 and usage["result_tokens"] > usage["args_tokens"]
    expected = (usage["result_tokens"] * 0.25 + usage["args_tokens"] * 2.00) / 1e6
    assert abs(usage["est_cost_usd"] - expected) < 1e-9


def test_the_response_is_measured_as_the_client_receives_it():
    assert as_agent_sees({"a": 1}) == '{\n  "a": 1\n}'
    assert as_agent_sees(None) == "" and as_agent_sees("text") == "text"
    assert call_usage({}, None) == {"args_tokens": 0, "result_tokens": 0, "est_cost_usd": 0.0}
