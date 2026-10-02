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
import agent_tasks as A
from harness import TOOL_PROMPT

MIX = [("tool_use", ["fix", "syntax", "retry"], 0.45), ("project_context", ["project"], 0.2),
       ("ask_first", ["git", "denied"], 0.15), ("too_big", ["too_big"], 0.08), ("compaction", ["retry"], 0.12)]
COMPACT_AT = 330        # tokens: small, so these runs really do fold their early steps away


def agent_conversations(rng, n):
    """n coding lessons, grouped by kind: {"tool_use": [...], ...}"""
    out = {kind: [] for kind, _, _ in MIX}
    for kind, runs, share in MIX:
        for _ in range(int(n * share)):
            run = rng.choice(runs)
            r = A.make_run(run, rng, system=TOOL_PROMPT, context_tokens=COMPACT_AT if kind == "compaction" else None)
            if r is None:
                continue
            if kind == "compaction" and not r["episodes"]:
                continue          # it never got long enough to need folding
            out[kind].append(A.mark_tools(r["messages"]))
    return out
