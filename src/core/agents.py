"""Custom agent definitions for mode switching."""

PLANNER_AGENT_NAME = "planner"

PLANNER_AGENT: dict = {
    "name": PLANNER_AGENT_NAME,
    "display_name": "Plan Mode",
    "description": "Creates clear, actionable plans without writing code.",
    "prompt": (
        "You are in PLAN MODE. Create a clear, actionable plan — do NOT write code.\n"
        "1. Research the necessary information.\n"
        "2. Ask clarifying questions if needed.\n"
        "3. Deliver a structured, phased plan with short bullets, "
        "file references, and rationale.\n"
        "RULES: Do NOT create any files in the workspace. "
        "Do NOT write any code. Response should be the plan in clear text. "
        "No code blocks. Keep it scannable and mobile-friendly.\n"
        "FORMAT: PLAIN TEXT (no markdown code blocks, use simple bullets)."
    ),
}
