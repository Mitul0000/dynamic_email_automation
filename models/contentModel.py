from pydantic import BaseModel

class Content(BaseModel):
    htmt:str
    subject:str
    