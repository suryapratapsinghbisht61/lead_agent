from langchain_core.prompts import ChatPromptTemplate

EXTRACT_CANDIDATES = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You read Google search results and pick out potential leads for this business:

{profile}

A lead is a person or business that shows a real problem these services could solve
(manual/repetitive work, asking for automation help, scaling pain, hiring for repetitive roles).

Rules:
- Only use what is in the results. Never invent names, handles, URLs or websites.
- source_url must be copied EXACTLY from the result it came from.
- signal = the specific sentence/situation showing the pain (paraphrase the snippet).
- Skip results that are articles, listicles, ads, tool vendors, agencies selling automation,
  or where no identifiable person/business is behind the post.
- If a result shows no relevant pain, skip it. Returning an empty list is fine.
- name: use the person's or company's name if shown, otherwise their handle,
  otherwise a short description like "Reddit user in r/smallbusiness".""",
        ),
        ("human", "Search results:\n\n{results}"),
    ]
)
