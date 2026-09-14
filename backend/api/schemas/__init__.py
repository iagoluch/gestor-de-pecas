"""Schemas Pydantic exclusivos do transporte HTTP."""

from .auth import LoginRequest, SessionUser
from .common import ErrorResponse, PageMeta

__all__ = ["ErrorResponse", "LoginRequest", "PageMeta", "SessionUser"]

