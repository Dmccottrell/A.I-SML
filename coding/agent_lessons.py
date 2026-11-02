"""
agent_lessons.py - Chat lessons for the coding helper (used by make_chat_data_v3.py).

WHAT THIS FILE DOES
    Practice runs from agent_tasks.py, turned into chat lessons in the real tool format. Every step is a real
    harness run, so the results the model reads are exactly what the tools return.

      kind            teaches
      --------------  ----------------------------------------------------------------------------
      tool_use        read -> change -> run the tests -> finish (also: diagnostics first; retry after a wrong fix)
      project_context follow the project notes (AGENTS.md) for how to run the tests
      ask_first       git changes ask permission first; if refused, say so and do not try again
      too_big         a huge request: say it is too big and suggest one small first step
      compaction      a long run whose old steps were folded into an "Earlier steps" list: carry on from it

    The tool-call and tool-result messages carry "tools": true, so chat.py writes the markers as the real special
    tokens. Only the assistant's messages are learned (the tool results are context, like user messages).
"""
# agent_tasks makes the practice runs; harness holds the system prompt that explains the tools to the model.
import agent_tasks as A
from harness import TOOL_PROMPT

# The recipe for the lesson set. Each row is (lesson kind, which practice-run types may be used for it, share).
# "share" is the fraction of the requested total n that this kind gets (the shares add up to 1.0).
MIX = [("tool_use", ["fix", "syntax", "retry"], 0.45), ("project_context", ["project"], 0.2),
       ("ask_first", ["git", "denied"], 0.15), ("too_big", ["too_big"], 0.08), ("compaction", ["retry"], 0.12)]
# How many tokens (small pieces of text) a run may reach before its oldest steps are folded into a short list.
COMPACT_AT = 330        # tokens: small, so these runs really do fold their early steps away


def agent_conversations(rng, n):
    """Make about n coding lessons, grouped by kind: {"tool_use": [...], ...}.

    rng is a random.Random (so the same seed gives the same lessons); n is the total wanted. Each value is a list of
    lessons, and each lesson is a list of chat messages. It exists so the data builder gets all kinds in one call."""
    # One empty list per kind, so every kind is present in the result even if it ends up with no lessons.
    out = {kind: [] for kind, _, _ in MIX}
    for kind, runs, share in MIX:
        # int() rounds down, so the kinds may add up to slightly fewer than n. That is fine.
        for _ in range(int(n * share)):
            # Pick one of the practice-run types allowed for this kind.
            run = rng.choice(runs)
            # Only "compaction" lessons use the small token limit; it makes the run fold its early steps.
            r = A.make_run(run, rng, system=TOOL_PROMPT, context_tokens=COMPACT_AT if kind == "compaction" else None)
            # make_run returns None when the run did not work out (e.g. tests never passed, or git is missing).
            if r is None:
                continue
            if kind == "compaction" and not r["episodes"]:
                continue          # it never got long enough to need folding
            # Flag the messages so the chat builder writes the tool markers as real special tokens.
            out[kind].append(A.mark_tools(r["messages"]))
    return out
