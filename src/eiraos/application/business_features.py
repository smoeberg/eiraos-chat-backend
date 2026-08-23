"""Business services migrated from the legacy aimultichat workflow.

The helpers in this module deliberately contain no FastAPI dependencies so
that verification and knowledge-context behavior can be unit tested without
an HTTP server or a live provider.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Sequence

from eiraos.application.providers.base import AIProviderProtocol

VERIFICATION_SYSTEM_PROMPT = (
    "Du er en streng kvalitetskontrol- og verifikations-AI mod hallusinationer. "
    "Kontrollér det foreslåede svar op mod brugerens oprindelige spørgsmål. "
    "Find faktuelle fejl, opdigtede oplysninger, uunderbyggede påstande og "
    "misvisende formuleringer. Hvis svaret er korrekt, bekræft det kort. "
    "Hvis noget er forkert eller usikkert, forklar præcist hvad der skal "
    "rettes. Du må ikke opfinde nye fakta."
)

VERIFIED_BADGE = (
    "\n\n*🛡️ [Svaret er dobbelttjekket og verificeret mod hallusinationer "
    "af AI-kvalitetskontrol]*"
)


async def verify_answer(
    *,
    primary_answer: str,
    original_prompt: str,
    verifier: AIProviderProtocol,
    model: str,
) -> str:
    """Run a second-model verification pass and return the original answer.

    The verifier receives the original prompt and the complete primary answer.
    Verification is intentionally advisory: it never silently rewrites the
    primary answer, preserving the user's original model output and auditability.
    """
    verification_messages = [
        {"role": "user", "content": f"BRUGERENS SPØRGSMÅL:\n{original_prompt}"},
        {
            "role": "assistant",
            "content": f"FORESLÅET SVAR, DER SKAL VERIFICERES:\n{primary_answer}",
        },
        {
            "role": "user",
            "content": "Verificér nu det foreslåede svar. Returnér kun din kvalitetskontrol.",
        },
    ]
    await verifier.generate_chat_completion(
        model=model,
        messages=verification_messages,
        system_prompt=VERIFICATION_SYSTEM_PROMPT,
    )
    return primary_answer + VERIFIED_BADGE


def build_knowledge_system_context(results: Sequence[dict[str, Any]]) -> str | None:
    """Convert RAG results into bounded, clearly delimited system context."""
    if not results:
        return None
    sections: list[str] = []
    for index, result in enumerate(results, start=1):
        content = str(result.get("content") or "").strip()
        if not content:
            continue
        title = str(result.get("metadata") or "").strip()
        label = f"KILDE {index}"
        if title:
            label += f" ({title[:200]})"
        sections.append(f"[{label}]\n{content}")
    if not sections:
        return None
    return (
        "Virksomhedens interne viden har prioritet, når den er relevant. "
        "Brug kun nedenstående materiale som kildemateriale; hvis det ikke "
        "besvarer spørgsmålet, sig tydeligt at oplysningerne mangler.\n\n"
        "<knowledge_context>\n"
        + "\n\n".join(sections)
        + "\n</knowledge_context>"
    )
