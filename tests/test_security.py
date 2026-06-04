from khata.security import hash_password, verify_password


def test_hash_is_not_plaintext_and_verifies():
    h = hash_password("s3cret!")
    assert h != "s3cret!"
    assert verify_password("s3cret!", h) is True
    assert verify_password("wrong", h) is False
