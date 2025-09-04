# app/user.py
from flask_login import UserMixin

class User(UserMixin):
    def __init__(self, id_, email, nombre):
        self.id = str(id_)
        self.email = email
        self.nombre = nombre
