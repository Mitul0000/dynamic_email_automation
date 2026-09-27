from pydantic import BaseModel

class User(BaseModel):
    email:str
    name:str
    index:str
    link:str = ""