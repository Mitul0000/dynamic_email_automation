import re
import logging
from models.userModel import User
from models.contentModel import Content
import ollama

logger = logging.getLogger(__name__)


SYSTEM_RULES = """
Write ONE personalized email from campaign instructions + recipient info.

RULES:
- Rewrite the campaign message in your own words for this recipient. Keep the same meaning/facts. Vary wording per recipient.
- Use ONLY facts given. Never invent info. Missing detail? Skip that line. Never use placeholders like [X].
- LINK: recipient may have a LINK field. Only mention a link if BOTH: (a) campaign instructions describe a link/action (e.g. "get your token"), AND (b) recipient's LINK is not "(none)". Use recipient's LINK exactly, as plain text in a <p> (e.g. "Get your token here: LINK"). If either condition fails, don't mention any link.
- End with exactly: Best regards, Incognito Organising Committee
- No ALL CAPS, no spam words (free, urgent, act now, guaranteed, click here, winner), max one "!".
- Subject: natural, plain, under 60 chars.
- HTML: only <p> <strong> <em> <br>, max one <hr>. Use <strong> only for key words. NO buttons, tables, divs, images, colors, inline CSS, styles. Plain black-on-white text only.

OUTPUT EXACTLY:
###SUBJECT_START###
subject line here
###SUBJECT_END###
###HTML_START###
email html here
###HTML_END###
"""


def contentGeneration(prompt: str, user: User, max_retries: int = 3) -> Content:
    logger.info(f"Starting content generation for user={user.email} (index={user.index})")

    user_link = (getattr(user, "link", "") or "").strip()

    user_message = f"""
    CAMPAIGN INSTRUCTIONS:
    \"\"\"{prompt}\"\"\"

    RECIPIENT:
    Name: {user.name}
    Email: {user.email}
    LINK: {user_link if user_link else "(none)"}
    """

    last_error = None
    for attempt in range(max_retries):
        temperature = 0.7 if attempt == 0 else 0.3
        logger.info(f"Attempt {attempt + 1}/{max_retries} for user={user.email} (temperature={temperature})")

        try:
            response = ollama.chat(
                model="qwen2.5-coder:1.5b",
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
            _validate_link_usage(content, user_link)
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
    html = html_match.group(1).strip()

    html = re.sub(r"^```(?:html)?\s*|\s*```$", "", html, flags=re.MULTILINE).strip()
    subject = re.sub(r"^```.*?```$", "", subject, flags=re.DOTALL).strip()

    return Content(subject=subject, html=html)


def _validate_no_placeholders(content: Content) -> None:
    placeholder_pattern = r"\[.*?\]"
    if re.search(placeholder_pattern, content.html) or re.search(placeholder_pattern, content.subject):
        raise ValueError(f"Output contains unresolved placeholder text: {content.html}")


def _validate_link_usage(content: Content, user_link: str) -> None:
    
    if user_link and user_link not in content.html:
        raise ValueError(
            f"Recipient link was not included verbatim in generated content: {user_link}"
        )