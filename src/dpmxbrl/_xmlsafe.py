"""Guards that keep XML parsing free of DTDs and external entities."""

from __future__ import annotations

from collections.abc import Callable
from xml.parsers import expat

from .model import ReportError

_CHUNK = 64 * 1024
_MAX_PROLOG = 1024 * 1024


def check_prolog(read: Callable[[int], bytes], label: str) -> bytes:
    """Reject an XML document whose prolog declares a DOCTYPE or ENTITY.

    DOCTYPE (and with it any ENTITY declaration) may only occur in the
    prolog, so scanning up to the first start tag is sufficient.

    Returns:
        bytes: The start of the document, its prolog included.

    Raises:
        ReportError: If the prolog contains a declaration or is too long.
    """
    head = b""
    while True:
        chunk = read(_CHUNK)
        head += chunk
        verdict = _scan(head)
        if verdict == "doctype":
            raise ReportError(
                f"{label}: DOCTYPE and ENTITY declarations are not allowed"
            )
        if verdict == "ok" or not chunk:
            return head
        if len(head) > _MAX_PROLOG:
            raise ReportError(f"{label}: XML prolog exceeds {_MAX_PROLOG} bytes")


def _decode(head: bytes) -> str:
    # Expat also detects UTF-16 without a byte order mark from a NUL in the
    # first two bytes, such as leading whitespace before the first tag.
    if head.startswith(b"\xff\xfe") or head[1:2] == b"\x00":
        return head.decode("utf-16-le", errors="ignore")
    if head.startswith(b"\xfe\xff") or head[:1] == b"\x00":
        return head.decode("utf-16-be", errors="ignore")
    return head.removeprefix(b"\xef\xbb\xbf").decode("latin-1")


def _scan(head: bytes) -> str:
    text = _decode(head).lstrip("﻿")
    index = 0
    while True:
        while index < len(text) and text[index] in " \t\r\n":
            index += 1
        if index >= len(text):
            return "more"
        if text.startswith("<?", index):
            end = text.find("?>", index + 2)
            if end < 0:
                return "more"
            index = end + 2
        elif text.startswith("<!--", index):
            end = text.find("-->", index + 4)
            if end < 0:
                return "more"
            index = end + 3
        elif text.startswith("<!", index) or len(text) - index < 2:
            return "doctype" if text.startswith("<!", index) else "more"
        else:
            return "ok"


def parse_catalog_rewrites(data: bytes, label: str) -> list[tuple[str, str]]:
    """Read ``rewriteURI``/``rewriteSystem`` entries from an XML catalog.

    The parser never loads external entities and rejects entity declarations.

    Returns:
        list[tuple[str, str]]: ``(start string, rewrite prefix)`` pairs.

    Raises:
        ReportError: If the catalog is not well-formed or declares entities.
    """
    rewrites: list[tuple[str, str]] = []
    parser = expat.ParserCreate(namespace_separator=" ")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    def reject_entity(*_: object) -> None:
        raise ReportError(f"{label}: ENTITY declarations are not allowed")

    def start(name: str, attributes: dict[str, str]) -> None:
        local = name.rpartition(" ")[2]
        if local == "rewriteURI":
            start_string = attributes.get("uriStartString")
        elif local == "rewriteSystem":
            start_string = attributes.get("systemIdStartString")
        else:
            return
        prefix = attributes.get("rewritePrefix")
        if start_string and prefix is not None:
            rewrites.append((start_string, prefix))

    parser.EntityDeclHandler = reject_entity
    parser.StartElementHandler = start
    try:
        parser.Parse(data, True)
    except expat.ExpatError as error:
        reason = expat.errors.messages[error.code]
        raise ReportError(
            f"{label}:{error.lineno}: invalid XML catalog ({reason})"
        ) from error
    return rewrites
