"""Tool definitions for Eve's multi-turn Claude calls.

WEB_SEARCH_TOOL is REUSED VERBATIM (identical literal, same type string
"web_search_20260209", same max_uses=5) from nero_core.research_agent.
hypothesis_gen.WEB_SEARCH_TOOL, per this branch's own spec (2.2: "reuse
WEB_SEARCH_TOOL's existing definition from hypothesis_gen.py, same tool
config"). It is REINLINED here rather than imported -- nero_core/eve/ never
imports from nero_core/research_agent/ (see test_eve_no_auto_wire.py) -- but
the two literals must be kept byte-identical; a test
(test_eve_llm_client.py) asserts this directly against Adam's own constant.

TWO ADDITIONAL, EVE-ONLY TOOLS (design decisions not dictated by the spec's
prose -- flagged in the closing report):

END_SESSION_TOOL -- the session-done signal (spec 2.4). A dedicated tool
Eve calls explicitly when finished, symmetric with web_search (both are just
entries in the same `tools` array). Chosen over inferring intent from prose
because it gives an explicit, loggable, unambiguous termination signal.

PROPOSE_HYPOTHESIS_TOOL -- NOT in the spec's own tool list, but needed to
answer a question the spec doesn't address: in a free-flowing multi-turn
conversation, how does a specific hypothesis PROPOSAL get distinguished from
Eve's general reasoning text, so it can be extracted into a scoreable
record? Rather than parsing prose for something that looks like a proposal
(fragile, ambiguous), Eve calls this tool once per hypothesis, with an
input_schema that accepts ANY JSON object -- deliberately unconstrained
(spec 2.7: "Whatever shape Eve proposes ... record it as-is. Do not force
her into Adam's schema."). This tool call is the ONLY thing that produces a
hypothesis record; free-form discussion in `text` blocks that never reaches
this tool is reasoning trail, not a proposal, and is not scored.
"""
from __future__ import annotations

WEB_SEARCH_TOOL: dict = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}

END_SESSION_TOOL_NAME = "end_session"

END_SESSION_TOOL: dict = {
    "name": END_SESSION_TOOL_NAME,
    "description": (
        "Call this when you are finished researching and proposing hypotheses for this "
        "session -- whether you found nothing worth proposing, proposed one hypothesis, or "
        "proposed many. This is the ONLY way a session ends on your own initiative (the other "
        "two ways a session can end are outside your control: a budget check refusing the next "
        "call, or a hard iteration safety cap). Calling this tool terminates the session "
        "immediately -- no further turns happen after it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "A short summary of what you researched and concluded this session.",
            },
            "n_hypotheses_proposed": {
                "type": "integer",
                "description": "How many hypotheses you proposed this session via propose_hypothesis (0 is a valid, honest answer).",
            },
        },
        "required": ["summary", "n_hypotheses_proposed"],
    },
}

PROPOSE_HYPOTHESIS_TOOL_NAME = "propose_hypothesis"

PROPOSE_HYPOTHESIS_TOOL: dict = {
    "name": PROPOSE_HYPOTHESIS_TOOL_NAME,
    "description": (
        "Call this to formally propose ONE trading hypothesis for scoring. You may call this "
        "any number of times in a session (zero, one, or many) -- there is no cap on how many "
        "hypotheses you propose, and no requirement to propose any. The 'hypothesis' input may "
        "be ANY JSON object -- if it happens to include structured_entry_rule/structured_exit_plan "
        "fields shaped like this project's existing rule DSL (fields: close, ma20, ma50, ma200, "
        "zscore20, atr14, rsi14, adx14, bb_lower, bb_upper, ret_1, volume; ops: gt, gte, lt, lte, "
        "eq, cross_above, cross_below; conditions are ANDed together), it will be backtested "
        "directly against real historical data. If it doesn't fit that DSL, it is still recorded "
        "and scored honestly as untestable-by-DSL -- that is useful information about what this "
        "platform's current tooling can and can't check, not a penalty -- so describe whatever "
        "shape actually captures your idea rather than forcing it into the DSL."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "hypothesis": {"type": "object", "description": "Any JSON object describing the proposed hypothesis, in whatever shape best captures it."},
        },
        "required": ["hypothesis"],
    },
}


def default_tools() -> list[dict]:
    return [WEB_SEARCH_TOOL, END_SESSION_TOOL, PROPOSE_HYPOTHESIS_TOOL]
