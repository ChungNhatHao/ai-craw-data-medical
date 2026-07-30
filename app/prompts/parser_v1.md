# Disease parser prompt v1.0.0

Extract only facts explicitly present in the supplied Markdown chunk.

Rules:

- Keep the source language; do not translate.
- Never add medical knowledge from memory.
- Use `null` or an empty list when a field is absent.
- Copy factual values closely enough that each value can be traced to the source.
- Do not return chain-of-thought or explanatory prose.
- Return data that validates against the provided structured schema.

