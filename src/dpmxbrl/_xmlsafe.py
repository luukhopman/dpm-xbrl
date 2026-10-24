"""Guards that keep XML parsing free of DTDs and external entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
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


def _parser(label: str) -> expat.XMLParserType:
    """Return a namespace-aware parser that rejects entity declarations.

    Returns:
        expat.XMLParserType: Names are reported as ``uri local``.
    """
    parser = expat.ParserCreate(namespace_separator=" ")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    def reject_entity(*_: object) -> None:
        raise ReportError(f"{label}: ENTITY declarations are not allowed")

    parser.EntityDeclHandler = reject_entity
    return parser


def _run(parser: expat.XMLParserType, data: bytes, label: str, what: str) -> None:
    try:
        parser.Parse(data, True)
    except expat.ExpatError as error:
        reason = expat.errors.messages[error.code]
        raise ReportError(
            f"{label}:{error.lineno}: invalid {what} ({reason})"
        ) from error


def parse_entry_points(data: bytes, label: str) -> list[str]:
    """Read the entry point document URLs of a ``taxonomyPackage.xml``.

    Returns:
        list[str]: The ``entryPointDocument`` ``href`` values.

    Raises:
        ReportError: If the file is not well-formed or declares entities.
    """
    found: list[str] = []
    parser = _parser(label)

    def start(name: str, attributes: dict[str, str]) -> None:
        if name.rpartition(" ")[2] == "entryPointDocument" and attributes.get("href"):
            found.append(attributes["href"])

    parser.StartElementHandler = start
    _run(parser, data, label, "taxonomy package metadata")
    return found


@dataclass(slots=True)
class ParsedSchema:
    """The parts of an XML schema the taxonomy lookups use."""

    namespace: str = ""
    prefix: str | None = None
    elements: dict[str, dict[str, str]] = field(default_factory=dict)
    ids: dict[str, str] = field(default_factory=dict)


_XSD = "http://www.w3.org/2001/XMLSchema"
_QNAME_ATTRIBUTES = frozenset({"type", "substitutionGroup"})


def parse_schema(data: bytes, label: str) -> ParsedSchema:
    """Read the target namespace, its prefix and global elements of a schema.

    Returns:
        ParsedSchema: Element attributes keyed by element name; ``type`` and
        ``substitutionGroup`` values and namespaced attribute names are in
        Clark notation.

    Raises:
        ReportError: If the schema is not well-formed or declares entities.
    """
    result = ParsedSchema()
    parser = _parser(label)
    scope: list[dict[str, str]] = []
    pending: dict[str, str] = {}

    def clark(value: str) -> str:
        prefix, separator, local = value.partition(":")
        if not separator:
            prefix, local = "", value
        for frame in reversed(scope):
            if prefix in frame:
                return f"{{{frame[prefix]}}}{local}" if frame[prefix] else local
        return value

    def start(name: str, attributes: dict[str, str]) -> None:
        nonlocal pending
        scope.append(pending)
        pending = {}
        uri, _, local = name.rpartition(" ")
        depth = len(scope)
        if depth == 1 and local == "schema":
            result.namespace = attributes.get("targetNamespace", "")
            result.prefix = next(
                (
                    prefix
                    for prefix, bound in scope[0].items()
                    if prefix and bound == result.namespace
                ),
                None,
            )
        elif depth == 2 and uri == _XSD and local == "element" and "name" in attributes:
            values: dict[str, str] = {}
            for key, value in attributes.items():
                namespace, _, attribute = key.rpartition(" ")
                if namespace:
                    values[f"{{{namespace}}}{attribute}"] = value
                else:
                    values[attribute] = (
                        clark(value) if attribute in _QNAME_ATTRIBUTES else value
                    )
            result.elements[attributes["name"]] = values
            if "id" in attributes:
                result.ids[attributes["id"]] = attributes["name"]

    def end(_: str) -> None:
        scope.pop()

    def start_namespace(prefix: str | None, uri: str | None) -> None:
        pending[prefix or ""] = uri or ""

    parser.StartNamespaceDeclHandler = start_namespace
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    _run(parser, data, label, "schema")
    return result
