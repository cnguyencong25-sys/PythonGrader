import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-change-me")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "fallback-jwt-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///database.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ---------- BẢO MẬT JWT ----------
    # JWT lưu trong HttpOnly Cookie -> JS không đọc được -> chống XSS đánh cắp token
    JWT_TOKEN_LOCATION = ["cookies"]
    JWT_COOKIE_SECURE = False          # Đặt True khi chạy HTTPS production
    JWT_COOKIE_HTTPONLY = True         # JS KHÔNG thể đọc cookie
    JWT_COOKIE_SAMESITE = "Lax"        # Chống CSRF cơ bản
    JWT_ACCESS_COOKIE_PATH = "/"
    JWT_COOKIE_CSRF_PROTECT = False    # Tắt CSRF double-submit cho dev (bật khi production)
    JWT_ACCESS_TOKEN_EXPIRES = 12 * 60 * 60    # 12 giờ