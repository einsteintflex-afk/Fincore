"""Private file storage.

* ``local`` (development/test): files under ``FINCORE_STORAGE_LOCAL_DIR``; downloads go through
  ``GET /api/v1/files/{token}`` where the token is a short-lived signed JWT naming the object.
* ``s3`` (production): any S3-compatible store (AWS S3, MinIO, Wasabi, DigitalOcean Spaces...). Objects are
  written with server-side encryption and downloads use presigned URLs. The bucket must block public access.

Objects are never addressable by a guessable or client-supplied name.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt

from app.core.config import settings
from app.core.errors import NotFound, Unauthorized
from app.core.security import JWT_ALG


class Storage:
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def signed_url(self, key: str, content_type: str) -> str: ...


def new_key(prefix: str) -> str:
    return f"{prefix}/{datetime.now(timezone.utc):%Y/%m}/{secrets.token_urlsafe(24)}"


def _file_token(key: str, content_type: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"typ": "file", "key": key, "ct": content_type, "iat": now,
                       "exp": now + timedelta(seconds=settings.storage_signed_url_ttl_seconds)},
                      settings.secret_key, algorithm=JWT_ALG)


def read_file_token(token: str) -> tuple[str, str]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALG])
    except jwt.PyJWTError as exc:
        raise Unauthorized("This link has expired", code="link_expired") from exc
    if payload.get("typ") != "file":
        raise Unauthorized("Invalid link")
    return payload["key"], payload["ct"]


class LocalStorage(Storage):
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:  # defence in depth against path traversal
            raise NotFound("File not found")
        return p

    def put(self, key: str, data: bytes, content_type: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes:
        p = self._path(key)
        if not p.is_file():
            raise NotFound("File not found")
        return p.read_bytes()

    def signed_url(self, key: str, content_type: str) -> str:
        return f"{settings.api_prefix}/files/{_file_token(key, content_type)}"


class S3Storage(Storage):
    def __init__(self) -> None:
        import boto3  # imported lazily: only needed when the S3 backend is configured

        self.bucket = settings.storage_s3_bucket
        self.client = boto3.client(
            "s3", region_name=settings.storage_s3_region or None,
            endpoint_url=settings.storage_s3_endpoint_url or None,
            aws_access_key_id=settings.storage_s3_access_key_id or None,
            aws_secret_access_key=settings.storage_s3_secret_access_key or None)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type,
                               ServerSideEncryption="AES256")

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def signed_url(self, key: str, content_type: str) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key, "ResponseContentType": content_type},
            ExpiresIn=settings.storage_signed_url_ttl_seconds)


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = S3Storage() if settings.storage_backend == "s3" else LocalStorage(settings.storage_local_dir)
    return _storage


def set_storage(storage: Storage | None) -> None:
    """Testing hook."""
    global _storage
    _storage = storage
