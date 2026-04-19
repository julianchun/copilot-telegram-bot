# code-review

A skill that performs thorough, structured code reviews.

## Usage

When asked to review code, follow this structured approach:

1. **Summary** — One-line description of what the change does.
2. **Correctness** — Check for bugs, logic errors, edge cases, and off-by-one issues.
3. **Security** — Flag any potential vulnerabilities (injection, auth bypass, data exposure).
4. **Performance** — Note any obvious inefficiencies or N+1 queries.
5. **Readability** — Suggest naming improvements or simplifications only when impactful.

Rules:
- Only flag issues that genuinely matter. Do not comment on style or formatting.
- Be specific: reference exact lines or code snippets.
- Suggest fixes, not just problems.
- Keep feedback concise and actionable.
