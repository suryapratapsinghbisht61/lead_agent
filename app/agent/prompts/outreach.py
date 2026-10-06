from langchain_core.prompts import ChatPromptTemplate

CHANNEL_RULES = {
    "linkedin_note": "LinkedIn connection note: max 300 characters total, no subject.",
    "x_dm": "X (Twitter) DM: casual, 2-4 short sentences, no subject.",
    "reddit_dm": "Reddit DM: mention their post naturally, friendly peer tone, no subject.",
    "email": "Cold email: include a short specific subject line, 60-100 words body.",
    "website_contact": "Message for their website contact form: 60-100 words, no subject.",
}

WRITE_OUTREACH = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You write outreach for this person and business:

{profile}

Write three things:
- about_them: 2-3 sentences on what this person/company does (only facts from the notes).
- how_i_can_help: 2-3 sentences: which of OUR services fits their problem and what concretely
  we'd build (e.g. "an AI agent that auto-replies to tier-1 support tickets").
- message: ONE sendable outreach message.

Message rules:
- Under 100 words. Human, plain, no hype, no buzzwords, no exclamation marks, no emojis.
- Open with something specific about them (their post, their role, their company).
- One sentence on what we could build for them. No pricing.
- End with a soft call to action (e.g. "open to a quick 15-min call?").
- Sign off with: {signature}
- Channel format: {channel_rule}""",
        ),
        (
            "human",
            """Lead: {name} ({category})
Company: {company}
Platform: {platform}
Signal: {signal}
Pain points: {pain_points}

Research notes:
{notes}""",
        ),
    ]
)
