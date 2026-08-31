"""
安全与加密模块。

负责生成或加载系统级密钥，并提供文本与 JSON 的对称加解密服务，
用于保护用户凭证（Cookie / Token 等敏感信息）。
"""
import json
import secrets

from cryptography.fernet import Fernet

from .config import settings

_key_file = settings.data_dir / "secret.key"


def _load_or_create_key() -> bytes:
    """
    加载主密钥，不存在时自动生成并持久化。

    优先使用环境变量 ``PUNCHCARD_SECRET_KEY``；否则从 ``data/secret.key``
    读取，若文件不存在则生成一个新密钥并写入，保证部署开箱即用。

    Returns:
        Fernet 主密钥（bytes）。
    """
    if settings.secret_key:
        return settings.secret_key.encode()
    if _key_file.exists():
        return _key_file.read_bytes().strip()
    key = Fernet.generate_key()
    _key_file.write_bytes(key)
    # Linux 下限制为仅属主可读写，避免同机其它用户读到加密密钥
    try:
        _key_file.chmod(0o600)
    except OSError:
        pass
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt_text(plain: str) -> str:
    """对称加密一段明文文本。

    Args:
        plain: 待加密的明文。

    Returns:
        加密后的字符串密文。
    """
    return _fernet.encrypt(plain.encode()).decode()


def decrypt_text(token: str) -> str:
    """对称解密一段密文文本。

    Args:
        token: 由 :func:`encrypt_text` 生成的密文。

    Returns:
        解密后的明文。

    Raises:
        cryptography.fernet.InvalidToken: 密钥不匹配或密文被篡改。
    """
    return _fernet.decrypt(token.encode()).decode()


def encrypt_json(data: dict) -> str:
    """把 JSON 可序列化的 dict 加密为字符串。

    Args:
        data: 需要加密存储的结构化数据。

    Returns:
        加密后的字符串密文。
    """
    return encrypt_text(json.dumps(data, ensure_ascii=False))


def decrypt_json(token: str) -> dict:
    """解密并反序列化 JSON 数据。

    Args:
        token: 由 :func:`encrypt_json` 生成的密文。

    Returns:
        解密还原出的 dict。
    """
    return json.loads(decrypt_text(token))


def generate_api_token() -> str:
    """生成一段安全的随机令牌（用于身份/接口凭证）。

    Returns:
        48 位十六进制随机字符串（24 字节安全随机数）。
    """
    return secrets.token_hex(24)
