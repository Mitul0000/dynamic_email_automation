import html as html_module
import os
import re
import logging

from models.userModel import User
from models.contentModel import Content
import ollama

logger = logging.getLogger(__name__)

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "logo.png")
POSTER_PATH = os.path.join(ASSETS_DIR, "poster.png")  # optional wide/landscape event graphic


# ---------------------------------------------------------------------------
# LLM prompt -- unchanged wording rules (full plain-text email: greeting +
# facts + sign-off). Only the model's *output text* is generated here; the
# visual design is applied afterwards from fixed HTML templates, so a 3B
# model never has to produce HTML/CSS itself.
# ---------------------------------------------------------------------------

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
- Do NOT include any links or URLs in the body -- any call-to-action button is added separately outside your text.
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


def _variant_index(user: User) -> int:
    try:
        return int(user.index)
    except (TypeError, ValueError):
        return 0


def _style_for(user: User) -> str:
    return STYLE_VARIANTS[_variant_index(user) % len(STYLE_VARIANTS)]


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

_LINK_INTENT_PATTERN = re.compile(r"\b(link|register|registration|rsvp|ticket|sign[\s-]?up|apply)\b", re.IGNORECASE)


def _campaign_wants_link(prompt: str) -> bool:
    """The campaign prompt itself must ask for a link/registration/ticket flow --
    otherwise we never show a button even if the spreadsheet happens to have a link column."""
    return bool(_LINK_INTENT_PATTERN.search(prompt or ""))


def contentGeneration(prompt: str, user: User, max_retries: int = 3) -> Content:
    logger.info(f"Starting content generation for user={user.email} (index={user.index})")

    raw_link = (getattr(user, "link", "") or "").strip()
    # Link is only ever used if BOTH the spreadsheet provided one AND the campaign
    # prompt actually asks for a link/registration/ticket flow.
    link = raw_link if (raw_link and _campaign_wants_link(prompt)) else ""

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
            html_out = _render_email(user=user, plain_text=content.html, link=link)
            logger.info(f"Successfully generated content for user={user.email} on attempt {attempt + 1}")
            return Content(subject=content.subject, html=html_out)
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

    body = re.sub(r"<[^>]+>", "", body)

    body = _EMOJI_PATTERN.sub("", body)
    subject = _EMOJI_PATTERN.sub("", subject)

    body = re.sub(
        r"\n*(best regards|warm regards|regards|sincerely|thanks|thank you)[\s,]*\n*(team\s*)?incognito.*$",
        "",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()

    lines = body.split("\n")
    if lines and re.match(r"^(dear|hey|hi|hello)\b.*[,!]\s*$", lines[0].strip(), re.IGNORECASE):
        rest = "\n".join(lines[1:]).lstrip("\n")
        body = lines[0].strip() + "\n\n" + rest

    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    body = f"{body}\n\nBest regards,\nIncognito Organising Committee"

    return Content(subject=subject.strip(), html=body)


def _validate_no_placeholders(content: Content) -> None:
    placeholder_pattern = r"\[.*?\]"
    if re.search(placeholder_pattern, content.html) or re.search(placeholder_pattern, content.subject):
        raise ValueError(f"Output contains unresolved placeholder text: {content.html}")


def _split_plain_text(plain_text: str) -> str:
    """Strip the fixed greeting line and sign-off block from the model's plain
    text (guaranteed by _parse_content), returning just the facts paragraphs --
    the template renders its own styled greeting heading and footer sign-off."""
    text = plain_text.strip()
    text = re.sub(
        r"\n*Best regards,\s*\n*Incognito Organising Committee\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    lines = text.split("\n")
    if lines and re.match(r"^(dear|hey|hi|hello)\b.*[,!]\s*$", lines[0].strip(), re.IGNORECASE):
        text = "\n".join(lines[1:]).lstrip("\n")
    return text.strip()


# ---------------------------------------------------------------------------
# GODFATHER THEME
#
# Colors pulled directly from the site's CSS variables (src/styles/globals.css):
#   --black #0a0705  --smoke #16110d  --parchment #ece1c6  --paper #e6dbbd
#   --gold #b8923f   --gold-bright #e0b563   --blood #5c0f16  --line rgba(184,146,63,.35)
#
# Fonts: the site uses custom files (TheGodfather.ttf, Goldoni.otf, Italianno.ttf)
# via @font-face. Email clients (Gmail, Outlook, most mobile mail apps) strip
# custom/embedded fonts almost universally, so there is no reliable way to ship
# those exact files in an email. Instead each role below maps to the closest
# *widely installed* font that reads the same way, with the same font stacks
# used consistently so the brand still feels intentional. To try a different
# look, just edit the three constants below -- nothing else needs to change.
# ---------------------------------------------------------------------------

COLOR_BG = "#0a0705"            # --black
COLOR_CARD_BG = "#16110d"       # --smoke
COLOR_CARD_BG_2 = "#1e1712"     # --smoke2
COLOR_PARCHMENT = "#ece1c6"     # --parchment (primary text)
COLOR_PARCHMENT_DIM = "#cabf9c" # --parchment-dim (secondary text)
COLOR_GOLD = "#b8923f"          # --gold
COLOR_GOLD_BRIGHT = "#e0b563"   # --gold-bright (headings, CTA)
COLOR_BLOOD = "#5c0f16"         # --blood (accent / CTA background)
COLOR_LINE = "rgba(184,146,63,0.35)"  # --line-bright, hairline rules

# Font-family fallback stacks standing in for the site's custom fonts
# (edit these three lines to change the whole email's typography):
FONT_DISPLAY = "Copperplate, 'Copperplate Gothic Std', Georgia, 'Times New Roman', serif"   # stands in for 'Godfather'
FONT_BODY = "'Iowan Old Style', 'Palatino Linotype', 'Book Antiqua', Georgia, serif"          # stands in for 'Goldoni'
FONT_SCRIPT = "'Brush Script MT', 'Segoe Script', cursive"                                    # stands in for 'Italianno'


def _logo_img(style: str) -> str:
    return f'<img src="cid:logo" alt="Incognito" style="{style}"/>'


def _poster_banner(style: str) -> str:
    """Wide/landscape hero image -- optional; sender skips this block entirely
    (via send_email.py) if assets/poster.png doesn't exist, so this never
    breaks the layout when no poster is supplied."""
    return f'<img src="cid:poster" alt="" width="100%" style="{style}"/>'


def _paragraphs_html(body_text: str) -> str:
    parts = [p.strip() for p in re.split(r"\n\s*\n", body_text) if p.strip()]
    if not parts:
        parts = [body_text.strip()]
    return "".join(
        f'<p style="margin:0 0 15px 0;font-family:{FONT_BODY};font-size:16px;line-height:1.7;'
        f'color:{COLOR_PARCHMENT};">{html_module.escape(p)}</p>'
        for p in parts
    )


def _button_html(link: str) -> str:
    if not link:
        return ""
    safe_link = html_module.escape(link, quote=True)
    return f"""
    <table role="presentation" cellpadding="0" cellspacing="0" style="margin:10px 0 4px 0;">
      <tr>
        <td style="border:1px solid {COLOR_GOLD};background-color:{COLOR_BLOOD};">
          <a href="{safe_link}" style="display:inline-block;padding:13px 34px;font-family:{FONT_BODY};
             font-size:14px;letter-spacing:0.12em;text-transform:uppercase;font-weight:bold;
             color:{COLOR_GOLD_BRIGHT};text-decoration:none;">View Details</a>
        </td>
      </tr>
    </table>
    """


def _card_open(width: int = 640) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/></head>
<body style="margin:0;padding:0;background-color:{COLOR_BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{COLOR_BG};">
<tr><td align="center" style="padding:28px 14px;">
<table role="presentation" width="{width}" cellpadding="0" cellspacing="0"
       style="max-width:{width}px;width:100%;background-color:{COLOR_CARD_BG};border:1px solid {COLOR_LINE};">"""


def _card_close() -> str:
    return "</table></td></tr></table></body></html>"


def _footer_row() -> str:
    return f"""<tr><td style="padding:20px 44px 34px 44px;">
<p style="margin:0;font-family:{FONT_BODY};font-size:12px;letter-spacing:0.08em;text-transform:uppercase;
   color:{COLOR_PARCHMENT_DIM};border-top:1px solid {COLOR_LINE};padding-top:16px;">
Best regards,<br/>Incognito Organising Committee</p>
</td></tr>"""


# --- Layout 1: landscape poster banner across the top, centered content below ---
def _template_banner(name: str, body_html: str, button_html: str, has_poster: bool) -> str:
    banner = (
        f'<tr><td style="line-height:0;">{_poster_banner("display:block;")}</td></tr>'
        if has_poster else ""
    )
    return f"""{_card_open(640)}
{banner}
<tr><td style="padding:26px 44px 6px 44px;text-align:center;">
{_logo_img("max-width:110px;height:auto;margin:0 auto 18px auto;")}
<p style="margin:0 0 6px 0;font-family:{FONT_SCRIPT};font-size:26px;color:{COLOR_GOLD};">An invitation from the family</p>
<h1 style="margin:0 0 22px 0;font-family:{FONT_DISPLAY};font-size:30px;letter-spacing:0.03em;color:{COLOR_GOLD_BRIGHT};">Hi {html_module.escape(name)},</h1>
</td></tr>
<tr><td style="padding:0 44px;text-align:left;">
{body_html}
</td></tr>
<tr><td style="padding:6px 44px 22px 44px;text-align:center;">
{button_html}
</td></tr>
{_footer_row()}
{_card_close()}"""


# --- Layout 2: landscape banner on the left, text on the right (table columns; stacks on narrow clients that ignore it, which is fine -- content stays readable) ---
def _template_split(name: str, body_html: str, button_html: str, has_poster: bool) -> str:
    left_cell = (
        f'<td valign="top" width="220" style="width:220px;background-color:{COLOR_CARD_BG_2};">'
        f'{_poster_banner("display:block;width:100%;height:100%;object-fit:cover;")}</td>'
        if has_poster else ""
    )
    left_col_open = "<tr>" if has_poster else ""
    left_col_close = "" if has_poster else ""
    right_width = 420 if has_poster else 640

    return f"""{_card_open(640)}
{left_col_open}
{left_cell}
<td valign="top" width="{right_width}" style="width:{right_width}px;padding:32px 40px;">
{_logo_img("max-width:100px;height:auto;margin:0 0 16px 0;")}
<p style="margin:0 0 4px 0;font-family:{FONT_SCRIPT};font-size:24px;color:{COLOR_GOLD};">An offer you cannot refuse</p>
<h1 style="margin:0 0 18px 0;font-family:{FONT_DISPLAY};font-size:26px;letter-spacing:0.02em;color:{COLOR_GOLD_BRIGHT};">Hi {html_module.escape(name)},</h1>
{body_html}
{button_html}
</td>
{left_col_close}
</tr>
{_footer_row()}
{_card_close()}"""


# --- Layout 3: ornate centered frame, poster as a wide strip mid-card ---
def _template_frame(name: str, body_html: str, button_html: str, has_poster: bool) -> str:
    mid_banner = (
        f'<tr><td style="padding:0 32px;line-height:0;">'
        f'<div style="border:1px solid {COLOR_LINE};">{_poster_banner("display:block;")}</div></td></tr>'
        if has_poster else ""
    )
    return f"""{_card_open(600)}
<tr><td style="padding:34px 40px 4px 40px;text-align:center;">
{_logo_img("max-width:120px;height:auto;margin:0 auto 14px auto;")}
<div style="border-top:1px solid {COLOR_LINE};border-bottom:1px solid {COLOR_LINE};padding:16px 0;margin-bottom:18px;">
<h1 style="margin:0;font-family:{FONT_DISPLAY};font-size:28px;letter-spacing:0.03em;color:{COLOR_GOLD_BRIGHT};">Hi {html_module.escape(name)},</h1>
</div>
</td></tr>
{mid_banner}
<tr><td style="padding:20px 40px 0 40px;text-align:left;">
{body_html}
</td></tr>
<tr><td style="padding:4px 40px 22px 40px;text-align:center;">
{button_html}
</td></tr>
{_footer_row()}
{_card_close()}"""


_TEMPLATES = [_template_banner, _template_split, _template_frame]


def _render_email(user: User, plain_text: str, link: str) -> str:
    idx = _variant_index(user) % len(_TEMPLATES)
    template_fn = _TEMPLATES[idx]

    facts_text = _split_plain_text(plain_text)
    body_html = _paragraphs_html(facts_text)
    button_html = _button_html(link)
    has_poster = os.path.exists(POSTER_PATH)

    return template_fn(name=user.name, body_html=body_html, button_html=button_html, has_poster=has_poster)