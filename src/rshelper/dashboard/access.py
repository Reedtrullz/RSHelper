"""Fail-closed bearer authorization for dashboard resources."""

import hmac


_PUBLIC_RESOURCES = frozenset({
    "public-market", "static", "sanitized-health", "capabilities",
})
_VALID_RESOURCES = _PUBLIC_RESOURCES | {"private-state", "daemon-control"}


def _bearer_matches(authorization: str | None, owner_token: str | None) -> bool:
    if not isinstance(authorization, str) or not isinstance(owner_token, str):
        return False
    if not owner_token:
        return False
    scheme, separator, presented = authorization.partition(" ")
    if (not separator or scheme.lower() != "bearer" or not presented
            or any(char.isspace() for char in presented)):
        return False
    try:
        supplied = presented.encode("ascii")
        expected = owner_token.encode("ascii")
    except UnicodeEncodeError:
        return False
    return hmac.compare_digest(supplied, expected)


def authorize(mode: str, authorization: str | None, owner_token: str | None,
              resource: str, mutation: bool) -> bool:
    """Return whether a request may reach its route callback.

    Public-demo has read access only to explicitly public static, market,
    sanitized-health, and capabilities resources. In owner mode, static,
    sanitized health, and capabilities remain public; market and private APIs
    require an exact Bearer token. Daemon-control also requires the handler's
    independent control flag.
    """
    if resource not in _VALID_RESOURCES:
        return False
    if mode == "public-demo":
        return not mutation and resource in _PUBLIC_RESOURCES
    if mode != "owner":
        return False
    if not mutation and resource in {"static", "sanitized-health", "capabilities"}:
        return True
    return _bearer_matches(authorization, owner_token)
