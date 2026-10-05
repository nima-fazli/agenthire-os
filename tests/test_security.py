from app.core.security import (
    hash_password,
    verify_password,
)


def test_hash_password_does_not_return_plain_password() -> None:
    password = "a-very-secure-password"

    password_hash = hash_password(
        password
    )

    assert password_hash != password


def test_hash_password_uses_different_salts() -> None:
    password = "a-very-secure-password"

    first_hash = hash_password(
        password
    )
    second_hash = hash_password(
        password
    )

    assert first_hash != second_hash


def test_verify_password_accepts_correct_password() -> None:
    password = "a-very-secure-password"

    password_hash = hash_password(
        password
    )

    assert verify_password(
        password,
        password_hash,
    ) is True


def test_verify_password_rejects_wrong_password() -> None:
    password_hash = hash_password(
        "a-very-secure-password"
    )

    assert verify_password(
        "wrong-password",
        password_hash,
    ) is False
