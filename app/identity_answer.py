"""
identity_answer.py - What Emvryx says when someone asks who or what it is.

WHAT THIS FILE DOES
    The owner's wording, the same for every model: "I am Emvryx, created by Darryl McCottrell."
    The app answers these questions itself instead of asking the model, because a model that learned its answers on an open base can still say
    another name. The question has to be short and really about the assistant ("who are you", "who made you", "what's your name", "are you ChatGPT",
    "introduce yourself"). A direct question about what it is built on gets one more true sentence, so nobody is told something false.
    Change the words below to change what it says everywhere.
"""
import re

NAME = "Emvryx"
CREATOR = "Darryl McCottrell"
ANSWER = f"I am {NAME}, created by {CREATOR}."
BASE_NOTE = " I'm built on an open foundation model."

MAX_WORDS = 14                      # a long message that happens to contain "who are you" is not a question about the assistant

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
_BUILT_ON = re.compile(
    r"\b(?:built|based|running|powered|trained)\s+(?:on|upon|by|with)\b|\bunderlying\b|\bfoundation\b|\bbase\s+model\b|\bunder\s+the\s+hood\b|"
    r"\bare\s+(?:you|u)\s+(?:chatgpt|gpt\S*|openai|claude|anthropic|gemini|bard|qwen|llama|mistral|deepseek|copilot|grok)\b|\bwhich\s+(?:model|llm)\b|\bwhat\s+(?:model|llm)\b", re.I)
_TASK = re.compile(r"^(write|draft|compose|translate|rewrite|summari[sz]e|make|create|generate|give me|list)\b", re.I)


def is_question(text):
    t = " ".join(str(text or "").split())
    if not t or len(t.split()) > MAX_WORDS or _TASK.match(t):
        return False
    return bool(_ABOUT_ME.search(t))


def answer(text):
    """The reply for a question about the assistant itself, or None for any other message."""
    if not is_question(text):
        return None
    return ANSWER + (BASE_NOTE if _BUILT_ON.search(str(text)) else "")
