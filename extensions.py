"""
Khởi tạo các extension DÙNG CHUNG cho toàn app.
Tách riêng file này để tránh import vòng (circular import).
"""
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager

db = SQLAlchemy()
bcrypt = Bcrypt()
jwt = JWTManager()