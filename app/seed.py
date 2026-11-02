import os
from dotenv import load_dotenv
from .database import Base, engine, SessionLocal
from .models import User
from .auth import hash_password

load_dotenv()


def run():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com").strip().lower()
        admin_password = os.getenv("ADMIN_PASSWORD", "ChangeMe123!")
        if not db.query(User).filter_by(email=admin_email).first():
            db.add(User(
                name="Admin",
                email=admin_email,
                password_hash=hash_password(admin_password),
                role="admin",
            ))
            print(f"Created default admin: {admin_email} / {admin_password} "
                  f"-- log in and change this password from your profile.")
            db.commit()
        print("Database ready.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
