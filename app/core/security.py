from pwdlib import PasswordHash

password_hasher = PasswordHash.recommended()

_dummy_password_hash = password_hasher.hash(
    "agenthire-dummy-password-for-timing-protection"
)


def hash_password(
    password: str,
) -> str:
    return password_hasher.hash(
        password
    )


def verify_password(
    password: str,
    password_hash: str,
) -> bool:
    return password_hasher.verify(
        password,
        password_hash,
    )


def verify_password_with_dummy(
    password: str,
    password_hash: str | None,
) -> bool:
    hash_to_verify = (
        password_hash
        if password_hash is not None
        else _dummy_password_hash
    )

    password_is_valid = verify_password(
        password,
        hash_to_verify,
    )

    return (
        password_hash is not None
        and password_is_valid
    )
