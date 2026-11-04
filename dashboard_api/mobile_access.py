"""移动查询凭据仅保存在当前 Windows 用户的系统凭据管理器。"""
import hashlib
import os
from pathlib import Path
import secrets

from .model_service_store import WindowsCredentials


def credential_target(root=None):
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    identity = hashlib.sha256(os.path.normcase(str(root)).encode()).hexdigest()[:24]
    return 'ReOps/MobileRead/' + identity


def load_token(*, credentials=None, root=None):
    value = os.getenv('REOPS_MOBILE_READ_TOKEN')
    if value is None:
        value = (credentials or WindowsCredentials()).get(credential_target(root))
    if not isinstance(value, str) or len(value) < 32 or not value.isascii() or any(c.isspace() for c in value):
        raise ValueError('mobile_access_not_configured')
    if value == os.getenv('REOPS_CONTROL_TOKEN'):
        raise ValueError('distinct_mobile_credential_required')
    return value


def provision_token(*, rotate=False, credentials=None, root=None):
    vault = credentials or WindowsCredentials()
    target = credential_target(root)
    try:
        existing = vault.get(target)
    except ValueError:
        existing = None
    if existing is not None and not rotate:
        if len(existing) < 32:
            raise ValueError('mobile_credential_invalid')
        return False
    vault.put(target, secrets.token_urlsafe(48))
    return True
