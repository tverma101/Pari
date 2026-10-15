#!/usr/bin/env python3
"""Small, text-safe error boundary for the Studio service.

Exceptions keep a stable client code and an internal diagnostic fingerprint.
They never carry an upstream body, prompt, document, or bearer token as their
client-visible message.
"""
from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any


class ClientErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    RESOURCE_LIMIT = "resource_limit"
    UNAUTHORIZED = "unauthorized"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_UNAVAILABLE = "model_unavailable"
    CANCELLED = "cancelled"
    BACKEND_PROTOCOL_ERROR = "backend_protocol_error"


_CLIENT_MESSAGES = {
    ClientErrorCode.INVALID_REQUEST: "The request could not be validated.",
    ClientErrorCode.RESOURCE_LIMIT: "The request exceeds a service limit.",
    ClientErrorCode.UNAUTHORIZED: "Authentication is required.",
    ClientErrorCode.MODEL_TIMEOUT: "The model request timed out.",
    ClientErrorCode.MODEL_UNAVAILABLE: "The model service is unavailable.",
    ClientErrorCode.CANCELLED: "The request was cancelled.",
    ClientErrorCode.BACKEND_PROTOCOL_ERROR: "The backend could not complete the request.",
}


def client_message(code: ClientErrorCode | str) -> str:
    try:
        return _CLIENT_MESSAGES[ClientErrorCode(code)]
    except (KeyError, ValueError):
        return _CLIENT_MESSAGES[ClientErrorCode.BACKEND_PROTOCOL_ERROR]


def client_error(
    code: ClientErrorCode | str,
    *,
    request_id: str | None = None,
    execution_id: str | None = None,
    retryable: bool | None = None,
) -> dict[str, Any]:
    """Return the only error shape allowed on the public wire."""
    value = code if isinstance(code, ClientErrorCode) else ClientErrorCode(code)
    payload: dict[str, Any] = {
        "code": value.value,
        "message": client_message(value),
    }
    if request_id is not None:
        payload["requestId"] = request_id
    if execution_id is not None:
        payload["executionId"] = execution_id
    if retryable is not None:
        payload["retryable"] = bool(retryable)
    return payload


def error_event(
    code: ClientErrorCode | str,
    *,
    request_id: str | None = None,
    execution_id: str | None = None,
    retryable: bool | None = None,
) -> dict[str, Any]:
    return {
        "version": 1,
        "type": "error",
        "error": client_error(
            code,
            request_id=request_id,
            execution_id=execution_id,
            retryable=retryable,
        ),
    }


def diagnostic_fingerprint(value: object) -> tuple[str, int]:
    """Hash arbitrary internal diagnostic text without retaining it."""
    text = str(value)
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16], len(text)


class ModelBackendError(Exception):
    """A model-side failure safe to map to a stable client error."""

    def __init__(
        self,
        code: ClientErrorCode | str,
        diagnostic: object = "",
        *,
        retryable: bool | None = None,
    ) -> None:
        self.code = code if isinstance(code, ClientErrorCode) else ClientErrorCode(str(code))
        self.diagnostic_sha256, self.diagnostic_chars = diagnostic_fingerprint(diagnostic)
        self.retryable = retryable
        super().__init__(client_message(self.code))


class ServiceLimitError(Exception):
    def __init__(self, field: str, limit: object) -> None:
        self.field = field
        self.limit = limit
        super().__init__(client_message(ClientErrorCode.RESOURCE_LIMIT))


class ServiceRequestError(Exception):
    def __init__(self, field: str = "request") -> None:
        self.field = field
        super().__init__(client_message(ClientErrorCode.INVALID_REQUEST))


def error_code_for_exception(exc: BaseException) -> ClientErrorCode:
    if isinstance(exc, ModelBackendError):
        return exc.code
    if isinstance(exc, ServiceLimitError):
        return ClientErrorCode.RESOURCE_LIMIT
    if isinstance(exc, ServiceRequestError):
        return ClientErrorCode.INVALID_REQUEST
    if isinstance(exc, TimeoutError):
        return ClientErrorCode.MODEL_TIMEOUT
    return ClientErrorCode.BACKEND_PROTOCOL_ERROR


def internal_diagnostic_fields(exc: BaseException) -> dict[str, Any]:
    """Fields safe to write to structured internal logs."""
    fields: dict[str, Any] = {"exceptionType": type(exc).__name__}
    fields["errorCode"] = error_code_for_exception(exc).value
    if isinstance(exc, ModelBackendError):
        fields["diagnosticSha256"] = exc.diagnostic_sha256
        fields["diagnosticChars"] = exc.diagnostic_chars
        if exc.retryable is not None:
            fields["retryable"] = bool(exc.retryable)
    elif isinstance(exc, (ServiceLimitError, ServiceRequestError)):
        fields["field"] = exc.field
    return fields


__all__ = [
    "ClientErrorCode",
    "ModelBackendError",
    "ServiceLimitError",
    "ServiceRequestError",
    "client_error",
    "client_message",
    "diagnostic_fingerprint",
    "error_code_for_exception",
    "error_event",
    "internal_diagnostic_fields",
]
