import bcrypt


def hash_password(plaintext: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
