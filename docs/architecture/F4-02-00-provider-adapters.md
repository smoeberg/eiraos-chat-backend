# F4-02 — Provider adapters

## Contract

Each concrete adapter translates the canonical `ChatProvider` request into one
provider-native request and translates provider output back into text chunks or
a final text response.

The adapter boundary guarantees:

- canonical temperature, output-token and system-instruction semantics are not dropped;
- provider credentials are sent in headers and never embedded in Gemini URLs;
- base URLs are normalized before endpoint construction;
- HTTP, transport and invalid-JSON failures become sanitized `EiraOSException` 502 errors;
- provider-reported stream errors fail closed;
- unknown SSE events and isolated malformed chunks do not terminate a valid stream;
- adapters do not perform authorization, model policy, persistence or cost accounting.

## Provider mapping

| Canonical field | OpenAI | Anthropic | Gemini |
| --- | --- | --- | --- |
| system prompt | system message | top-level `system` | `systemInstruction` |
| temperature | `temperature` | `temperature` | `generationConfig.temperature` |
| max tokens | `max_tokens` | `max_tokens` | `generationConfig.maxOutputTokens` |
| streaming | chat-completions SSE | Messages SSE | `streamGenerateContent` SSE |

Capability discovery remains F4-03. Failure isolation beyond adapter error
normalization remains F4-04.
