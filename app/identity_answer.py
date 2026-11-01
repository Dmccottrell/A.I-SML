"""
identity_answer.py - What Emvryx says when someone asks who or what it is.

WHAT THIS FILE DOES
    The owner's wording, the same for every model: "I am Emvryx, created by Darryl McCottrell."
    The app answers these questions itself instead of asking the model, because a model that learned its answers on an open base can still say
    another name. The question has to be short and really about the assistant ("who are you", "who made you", "what's your name", "are you ChatGPT",
    "introduce yourself"). A direct question about what it is built on gets one more true sentence, so nobody is told something false.
    Change the words below to change what it says everywhere.

    Where it fits: chat_turn.start_turn() calls answer() first; if it returns text, that text is the reply and no model is run.
    The patterns are regexes (text patterns): re.I ignores capitals, \\b marks a word edge, \\s is a space, (?:...) is a group, | means "or".
"""
import re

NAME = "Emvryx"
CREATOR = "Darryl McCottrell"
ANSWER = f"I am {NAME}, created by {CREATOR}."
# Added only when the person asks directly what it is built on; this keeps the answer true.
BASE_NOTE = " I'm built on an open foundation model."

MAX_WORDS = 14                      # a long message that happens to contain "who are you" is not a question about the assistant

# Recognises questions about the assistant itself ("who are you", "what's your name", "who made you", "are you <another assistant>", "introduce yourself").
# The first alternative skips things like "who are you going to ..." (a question about someone else's plans). The "$" in one alternative means
# "end of the message". The whole pattern is split over several quoted lines that Python joins into one string.
_ABOUT_ME = re.compile(
    r"\b(who|what)\s+(are|r)\s+(you|u)\b(?!\s+(?:going|gonna|voting|seeing|meeting|talking|texting|calling|bringing|taking|doing|wearing|reading|watching|planning))|"
    r"\bwhat(?:'s|s| is)\s+(?:your|ur)\s+name\b|\byour\s+name\b\s*\??$|\bwho\s+(?:are|is)\s+this\b|"
    r"\bwho\s+(?:made|created|built|developed|trained|designed|invented|programmed|owns|runs)\s+(?:you|u)\b|"
    r"\bwho(?:'s|s| is)\s+(?:your|ur)\s+(?:creator|developer|maker|owner|author|builder|founder)\b|"
    r"\bwho(?:'s|s| is)\s+behind\s+(?:you|emvryx)\b|\bwho\s+do\s+you\s+(?:work|belong)\s+(?:for|to)\b|"
    r"\b(?:what|which)\s+(?:model|ai|llm|bot|chatbot|assistant|company|version)\s+(?:are|r)\s+(?:you|u)\b|"
    r"\bwhat\s+(?:company|team|person)\s+(?:made|created|built|trained)\s+(?:you|u)\b|"
    r"\b(?:introduce|describe|explain)\s+yourself\b|\btell\s+me\s+(?:about|who)\s+yourself\b|\btell\s+me\s+about\s+you\b|"
    r"\bare\s+(?:you|u)\s+(?:chatgpt|gpt\S*|openai|claude|anthropic|gemini|bard|qwen|llama|mistral|deepseek|copilot|siri|alexa|grok|an?\s+ai|a\s+bot|a\s+robot|(?:a\s+)?human|a\s+person|real)\b|"
    r"\bwhat\s+is\s+emvryx\b|\bwho\s+is\s+emvryx\b",
    re.I)
# Recognises a direct question about what the assistant is built on or which model it is; these get the extra BASE_NOTE sentence.
_BUILT_ON = re.compile(
    r"\b(?:built|based|running|powered|trained)\s+(?:on|upon|by|with)\b|\bunderlying\b|\bfoundation\b|\bbase\s+model\b|\bunder\s+the\s+hood\b|"
    r"\bare\s+(?:you|u)\s+(?:chatgpt|gpt\S*|openai|claude|anthropic|gemini|bard|qwen|llama|mistral|deepseek|copilot|grok)\b|\bwhich\s+(?:model|llm)\b|\bwhat\s+(?:model|llm)\b", re.I)
# A message that starts like a job to do ("write", "translate", "make"...) is a task, not a question about the assistant.
_TASK = re.compile(r"^(write|draft|compose|translate|rewrite|summari[sz]e|make|create|generate|give me|list)\b", re.I)


def is_question(text):
    """True when `text` is a short question about who or what the assistant is."""
    # Squeeze whitespace; None becomes "".
    t = " ".join(str(text or "").split())
    # Empty, too long, or a task: not an identity question.
    if not t or len(t.split()) > MAX_WORDS or _TASK.match(t):
        return False
    return bool(_ABOUT_ME.search(t))


def answer(text):
    """The reply for a question about the assistant itself, or None for any other message."""
    if not is_question(text):
        return None
    # The fixed answer, plus the extra sentence when the question is about what it is built on.
    return ANSWER + (BASE_NOTE if _BUILT_ON.search(str(text)) else "")
