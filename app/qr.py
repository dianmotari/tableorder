"""Helpers for table QR tokens.

Tokens must be unguessable (at least 128 random bits). secrets.token_urlsafe(16)
gives ~128 bits of randomness in a URL-safe string. The QR encodes
/t/<token>, never the table number, so people cannot guess other tables.
"""
import secrets


def new_token() -> str:
    return secrets.token_urlsafe(16)