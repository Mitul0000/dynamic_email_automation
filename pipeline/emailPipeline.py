import logging

from models.userModel import User
from models.contentModel import Content
from core.userDetailsExtractor import extract
from core.email_content_generator import contentGeneration
from core.send_email import getMailRequest

logger = logging.getLogger(__name__)


def runEmailPipeline(excel_path: str, prompt: str, attachment_path: str = "",start_index:int=1) -> None:

    logger.info(f"Pipeline started. excel_path={excel_path}, attachment={bool(attachment_path)}")
    users: list[User] = extract(excel_path,start_index)
    logger.info(f"Extracted {len(users)} users from {excel_path}")
    if not users:
        logger.warning("No users found in the provided file. Aborting pipeline.")
        return
    
    payload: list[dict[str, Content | User]] = []

    for user in users:
        try:
            content: Content = contentGeneration(prompt, user)
        except RuntimeError as e:
            logger.error(f"Skipping user={user.email} (index={user.index}) - content generation failed: {e}")
            continue

        payload.append({"user": user, "content": content})

    if not payload:
        logger.error("No content was successfully generated for any user. Aborting send step.")
        return

    logger.info(f"Generated content for {len(payload)}/{len(users)} users. Starting send step.")
    getMailRequest(payload, filepath=attachment_path)
    logger.info("Pipeline finished.")
