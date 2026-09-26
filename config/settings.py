from pydantic_settings import BaseSettings
from dotenv import load_dotenv
import os

load_dotenv()

class Settings(BaseSettings):
    email1:str = os.getenv('userId1')
    email2:str = os.getenv('userId2')
    password1:str = os.getenv('password1')
    password2:str = os.getenv('password2')
    limit_for_each_mail:int = 150
