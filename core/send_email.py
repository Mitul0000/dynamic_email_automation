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



logger = logging.getLogger(__name__)

setting = Settings()
port = 587
SMTP_SERVER = "live.smtp.mailtrap.io"

track_mail_send =[]


def receiveMailRequest(users:list[dict[str,Content | User]],filepath:str = ""):
    
    for index,user in enumerate(users):
        userDetails = user["user"]
        content = user["content"]

        if userDetails.index in track_mail_send:
            continue
        
        if(index>=setting.limit_for_each_mail):
            track_mail_send.append(sendMail(userDetails,content,2,filepath))
        else:
            track_mail_send.append(sendMail(userDetails,content,1,filepath))
        

def sendMail(user:User,content:Content,mailId:int,filepath:str)->int:
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
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject
    body = content.htmt
    message.attach(MIMEText(body, "html"))

    if filepath:
        filename = os.path.basename(filepath)
        with open(filepath,"rb") as attachment:
            part = MIMEBase("application","octet-stream")
            part.set_payload(attachment.read())

        encoders.encode_base64(part)

        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=filename
        )
        message.attach(part)

    text = message.as_string()
    try:
        with smtplib.SMTP(SMTP_SERVER, 587) as server:
            server.starttls()
            server.login(login, password)
            server.sendmail(
                sender_email, receiver_email, text
            )
        logger.info(f"Email sent successfully to {user.index}. {user.email}")
        return user.index
    except Exception as e:
        logger.error(f"Email sent failed for {user.index}. {user.email}")
        return None
