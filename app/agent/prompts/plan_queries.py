from langchain_core.prompts import ChatPromptTemplate

PLAN_QUERIES = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You plan Google searches that find potential customers for this business:

{profile}

Write search queries that surface PEOPLE or BUSINESSES publicly showing a problem these services solve:
- complaints about manual/repetitive work ("spending hours on data entry", "drowning in support tickets")
- asking for tools or help to automate something
- founders posting about scaling pains or no bandwidth
- companies hiring for repetitive roles (data entry, support, ops, admin)

Rules:
- Each query is plain Google search words (use quotes for exact phrases, OR between alternatives).
- Do NOT include any "site:" operator. It is added automatically per platform.
- Keep queries short (3-10 words) so Google returns results.
- Vary the angle: different pains, different roles, different phrasings.
- Never repeat a query from the "already used" list.""",
        ),
        (
            "human",
            """Platforms: {platforms}
Niche focus: {niche}
Extra keywords: {keywords}
Lead types wanted: {categories}
Queries per platform: {per_platform}

Already used (do not repeat):
{past_queries}""",
        ),
    ]
)
