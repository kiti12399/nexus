from cryptography.fernet import Fernet


class KeyCipher:
    def __init__(self, encryption_key: str) -> None:
        self._fernet = Fernet(encryption_key.encode("utf-8"))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")


def new_fernet_key() -> str:
    return Fernet.generate_key().decode("utf-8")


def print_new_key() -> None:
    print(new_fernet_key())


if __name__ == "__main__":
    print_new_key()
