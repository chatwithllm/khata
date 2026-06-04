from werkzeug.security import check_password_hash, generate_password_hash


def hash_password(plain: str) -> str:
    return generate_password_hash(plain, method="pbkdf2:sha256")


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    return check_password_hash(hashed, plain)
