import pandas as pd
from models.userModel import User

def extract(input_path: str) -> list[User]:
    data_frame = pd.read_excel(input_path)

    name_col = next(c for c in data_frame.columns if "name" in c.lower())
    email_col = next(c for c in data_frame.columns if "email" in c.lower())

    result = data_frame[[name_col, email_col]].dropna(how="all")

    users: list[User] = []
    for i, row in enumerate(result.itertuples(index=False), start=1):
        name = str(row[0]).strip() if pd.notna(row[0]) else ""
        email = str(row[1]).strip() if pd.notna(row[1]) else ""
        users.append(User(email=email, name=name, index=str(i)))

    return users