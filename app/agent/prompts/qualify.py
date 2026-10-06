from langchain_core.prompts import ChatPromptTemplate

QUALIFY = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You qualify sales leads for this business:

{profile}

Decide:
1. category (exactly one):
   - startup: early-stage company or founder
   - company: established business or SMB with a team
   - individual: solo person, freelancer, creator, coach or consultant
2. pain_points: specific problems THESE services can solve, based only on the evidence.
3. fit_score 1-10:
   - 8-10: clear, specific, current pain we can solve + a business that can pay
   - 5-7: plausible pain, some uncertainty
   - 1-4: no real fit, vague, a competitor, a student, just wants free advice, or a tool vendor
   Small bonus (+1) for preferred categories or boosted niches listed in the profile.
   Never inflate the score. If there is no real fit, say so.
4. fit_reason: ONE line.
Today is {today}.""",
        ),
        (
            "human",
            """Lead: {name}
Platform: {platform}
Company: {company}
Signal that flagged them: {signal}
Source: {source_url}

Research notes:
{notes}""",
        ),
    ]
)
