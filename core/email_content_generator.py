import re
import logging
from models.userModel import User
from models.contentModel import Content
import ollama

logger = logging.getLogger(__name__)


SYSTEM_RULES = """
You are an email content generator. Write ONE personalized email based on the campaign facts and recipient details given by the user.

The email MUST follow this exact structure, in this order:

1. A short one-line greeting to the recipient by name (e.g. "Hi {name}," or "Hello {name},"). Nothing else on this line.
2. A blank line.
3. The body: present the campaign facts given by the user, in the order they were given, in your own words. Do not invent facts that were not given. Do not omit facts that were given.
4. A blank line.
5. Exactly this closing, nothing else after it:
Best regards,
Incognito Organising Committee

RULES:
- Do NOT copy the campaign instructions verbatim if they are written as full sentences -- restate the facts in your own words, but keep every fact that was given.
- Different recipients must NOT receive identically-worded emails. Follow the STYLE DIRECTIVE given for this recipient to vary sentence structure and phrasing.
- NO EMOJIS anywhere in the subject or body. None. Not even one.
- No ALL CAPS words, no spam-trigger words or phrases (free, urgent, act now, guaranteed, click here, winner, congratulations, limited time, don't miss out, successfully confirmed, thrilled, can't wait), max one "!" in the whole email.
- No markdown, no HTML tags. Plain text only.
- Never write placeholders like [Insert Date] or [Your Name].
- Subject: a short natural subject line, under 60 chars, no emojis/caps/symbols, clearly SHORTER than the body, and must differ in phrasing from other recipients' subjects.

OUTPUT EXACTLY THIS FORMAT, NOTHING ELSE:

###SUBJECT_START###
subject line here
###SUBJECT_END###
###HTML_START###
Hi {name},

body here

Best regards,
Incognito Organising Committee
###HTML_END###
"""

STYLE_VARIANTS = [
    "Warm and personal tone. Keep paragraphs short (1-2 sentences).",
    "Concise and informative tone. State details plainly, minimal flourish, slightly more formal register.",
    "Enthusiastic-but-understated tone. Short, punchy sentences.",
    "Conversational and friendly tone, as if written by a peer on the organising team. Use contractions, keep it light.",
    "Structured tone. One short sentence on what to expect, then one short sentence on next steps.",
]


def _style_for(user: User) -> str:
    try:
        idx = int(user.index)
    except (TypeError, ValueError):
        idx = 0
    return STYLE_VARIANTS[idx % len(STYLE_VARIANTS)]


# Emoji stripping safety net, in case the model adds one anyway despite the rule
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "]+",
    flags=re.UNICODE,
)


def contentGeneration(prompt: str, user: User, max_retries: int = 3) -> Content:
    logger.info(f"Starting content generation for user={user.email} (index={user.index})")

    user_message = f"""
    CAMPAIGN FACTS (use these facts, restated in your own words, keep every fact given):
    \"\"\"{prompt}\"\"\"

    STYLE DIRECTIVE FOR THIS RECIPIENT (follow this closely -- other recipients get different directives):
    {_style_for(user)}

    RECIPIENT:
    Name: {user.name}
    Email: {user.email}
    """

    last_error = None
    for attempt in range(max_retries):
        temperature = 0.7 if attempt == 0 else 0.3
        logger.info(f"Attempt {attempt + 1}/{max_retries} for user={user.email} (temperature={temperature})")

        try:
            response = ollama.chat(
                model="llama3.2:3b",
                messages=[
                    {"role": "system", "content": SYSTEM_RULES},
                    {"role": "user", "content": user_message},
                ],
                options={"temperature": temperature},
            )
        except Exception as e:
            logger.error(f"Ollama call failed for user={user.email} on attempt {attempt + 1}: {e}")
            last_error = e
            continue

        raw_output = response["message"]["content"].strip()

        try:
            content = _parse_content(raw_output)
            _validate_no_placeholders(content)
            logger.info(f"Successfully generated content for user={user.email} on attempt {attempt + 1}")
            return content
        except ValueError as e:
            logger.warning(f"Validation failed for user={user.email} on attempt {attempt + 1}: {e}")
            last_error = e
            continue

    logger.error(f"Failed to generate content for user={user.email} after {max_retries} attempts: {last_error}")
    raise RuntimeError(f"Failed after {max_retries} attempts: {last_error}")


def _parse_content(raw_output: str) -> Content:
    subject_match = re.search(
        r"###SUBJECT_START###\s*(.*?)\s*###SUBJECT_END###",
        raw_output,
        re.DOTALL,
    )
    html_match = re.search(
        r"###HTML_START###\s*(.*?)\s*###HTML_END###",
        raw_output,
        re.DOTALL,
    )

    if not subject_match or not html_match:
        raise ValueError(
            f"Could not extract subject/html from model output.\nRaw output:\n{raw_output}"
        )

    subject = subject_match.group(1).strip()
    body = html_match.group(1).strip()

    body = re.sub(r"^```\s*|\s*```$", "", body, flags=re.MULTILINE).strip()
    subject = re.sub(r"^```.*?```$", "", subject, flags=re.DOTALL).strip()

    # strip any stray HTML tags the model still slips in
    body = re.sub(r"<[^>]+>", "", body)

    # strip emojis (safety net beyond the prompt rule)
    body = _EMOJI_PATTERN.sub("", body)
    subject = _EMOJI_PATTERN.sub("", subject)

    # strip any closing/signature the model added on its own so we can
    # re-append a single, correctly-spaced one below
    body = re.sub(
        r"\n*(best regards|warm regards|regards|sincerely|thanks|thank you)[\s,]*\n*(team\s*)?incognito.*$",
        "",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()

    # enforce: blank line after the opening greeting line (e.g. "Hi Mitul,")
    lines = body.split("\n")
    if lines and re.match(r"^(dear|hey|hi|hello)\b.*[,!]\s*$", lines[0].strip(), re.IGNORECASE):
        rest = "\n".join(lines[1:]).lstrip("\n")
        body = lines[0].strip() + "\n\n" + rest

    # collapse any accidental triple+ blank lines down to exactly one blank line
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    # enforce: exactly one blank line before the closing, closing appended once
    body = f"{body}\n\nBest regards,\nIncognito Organising Committee"

    return Content(subject=subject.strip(), html=body)


def _validate_no_placeholders(content: Content) -> None:
    placeholder_pattern = r"\[.*?\]"
    if re.search(placeholder_pattern, content.html) or re.search(placeholder_pattern, content.subject):
        raise ValueError(f"Output contains unresolved placeholder text: {content.html}")