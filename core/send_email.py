import smtplib
import os
import logging

from models.userModel import User
from models.contentModel import Content
from config.settings import Settings
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.utils import formatdate, make_msgid


logger = logging.getLogger(__name__)

setting = Settings()
SMTP_SERVER = "smtp.titan.email"

LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "logo.png")
POSTER_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "poster.png")

track_mail_send = []


def getMailRequest(users: list[dict[str, Content | User]], filepath: str = ""):
    for index, user in enumerate(users):
        userDetails: User = user["user"]
        content: Content = user["content"]

        if userDetails.index in track_mail_send:
            continue
        if index >= setting.limit_for_each_mail:
            track_mail_send.append(sendMail(userDetails, content, 2, filepath))
        else:
            track_mail_send.append(sendMail(userDetails, content, 1, filepath))


def _build_cid_image(path: str, cid: str) -> MIMEImage | None:
    if not os.path.exists(path):
        logger.warning(f"Image not found at {path} (cid:{cid}) -- sending without it")
        return None
    with open(path, "rb") as f:
        img = MIMEImage(f.read())
    img.add_header("Content-ID", f"<{cid}>")
    img.add_header("Content-Disposition", "inline", filename=os.path.basename(path))
    return img


def sendMail(user: User, content: Content, mailId: int, filepath: str) -> str | None:
    if mailId == 1:
        login = setting.email1
        password = setting.password1
        sender_email = setting.email1
    else:
        login = setting.email2
        password = setting.password2
        sender_email = setting.email2

    subject = content.subject
    receiver_email = user.email
    html_body = content.html

    # multipart/related holds the HTML + inline logo/poster images together
    related = MIMEMultipart("related")
    related.attach(MIMEText(html_body, "html"))

    logo_part = _build_cid_image(LOGO_PATH, "logo")
    if logo_part is not None:
        related.attach(logo_part)

    poster_part = _build_cid_image(POSTER_PATH, "poster")
    if poster_part is not None:
        related.attach(poster_part)

    if filepath:
        # multipart/mixed wraps the related part + a real file attachment
        message = MIMEMultipart("mixed")
        message.attach(related)

        filename = os.path.basename(filepath)
        with open(filepath, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        message.attach(part)
    else:
        message = related

    display_name = "Incognito Organising Committee"
    message["From"] = f"{display_name} <{sender_email}>"
    message["To"] = receiver_email
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=sender_email.split("@")[-1])
    message["Reply-To"] = sender_email

    text = message.as_string()
    try:
        with smtplib.SMTP(SMTP_SERVER, 587) as server:
            server.starttls()
            server.login(login, password)
            server.sendmail(sender_email, receiver_email, text)
        logger.info(f"Email sent successfully to {user.index}. {user.email}")
        return user.index
    except Exception as e:
        logger.error(f"Email sent failed for {user.index}. {user.email} with error: {e}")
        return None