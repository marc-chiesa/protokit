"""Shared helpers for JUnit XML emission.

Built on ``xml.etree.ElementTree`` to keep escaping and
encoding correct for non-ASCII text and surrogate pairs without
hand-rolling. Adds two protokit-specific concerns:

1. **Ill-formed code-point scrubbing.** XML 1.0's ``Char``
   production excludes far more than the ASCII controls — see
   :data:`_XML_ILL_FORMED` for the full set. ElementTree will
   happily accept any of them and produce parser-rejected output;
   :func:`xml_safe_text` strips them before they reach the tree.

2. **Apache Ant JUnit conformance.** The vendored
   ``tests/fixtures/junit-xml/JUnit.xsd`` (Apache Ant reference)
   marks ``timestamp``, ``hostname``, ``tests``, ``failures``,
   ``errors``, ``time`` as required on ``<testsuite>`` and
   ``name``, ``classname``, ``time`` as required on ``<testcase>``.
   :func:`make_testsuite` and :func:`make_testcase` populate the
   full set with deterministic defaults so snapshot tests stay
   stable and downstream consumers stop complaining about missing
   attributes.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

# Code points outside XML 1.0's Char production, which is:
#   #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]
# Anything else makes the document non-well-formed, so these are
# dropped rather than escaped — there is no escape that rescues
# them (a numeric reference to a non-Char is equally invalid, which
# is exactly how a lone surrogate fails: ElementTree emits
# "&#55296;" and the parser rejects the reference).
#
# Three disjoint groups, all reachable from real data:
#   - ASCII controls: hostile input, terminal escapes in messages.
#   - Lone surrogates: filenames that failed to decode cleanly
#     (surrogateescape) on filesystems that permit them.
#   - U+FFFE / U+FFFF: valid UTF-8 and legal protobuf string
#     content, so a map key or field value carries them straight in.
#
# Deliberately NOT scrubbed: the plane noncharacters (U+1FFFE,
# U+2FFFE, ...) and the C1 range (\x7f-\x9f). Both are *discouraged*
# by the spec but are inside Char, i.e. well-formed. This helper's
# contract is well-formedness, not the discouraged set — widening it
# would silently drop legitimate user data for no parser benefit.
_XML_ILL_FORMED = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]"
)

# Deterministic timestamp / hostname so snapshot tests don't
# pick up wall-clock or machine-name drift. Future flag could
# opt in to real values for live CI runs.
DETERMINISTIC_TIMESTAMP = "1970-01-01T00:00:00"
DETERMINISTIC_HOSTNAME = "localhost"


def xml_safe_text(text: str) -> str:
    """Strip code points outside XML 1.0's ``Char`` production.

    Every caller-supplied string reaching the tree — attribute or
    text, in this module or in a caller that sets an attribute
    directly — must pass through here, because ElementTree has no
    check of its own and the failure is silent until a consumer
    tries to parse the file.

    Accepts the empty string. Preserves all other content
    including newlines, tabs, and arbitrary Unicode (ElementTree
    handles encoding) — see :data:`_XML_ILL_FORMED` for what is
    deliberately left alone.
    """
    if not text:
        return ""
    return _XML_ILL_FORMED.sub("", text)


def make_testsuite(
    *,
    name: str,
    tests: int,
    failures: int,
    errors: int,
    timestamp: str = DETERMINISTIC_TIMESTAMP,
    hostname: str = DETERMINISTIC_HOSTNAME,
    time: str = "0",
) -> ET.Element:
    """Construct a ``<testsuite>`` element with all xsd-required attrs.

    The Apache Ant JUnit xsd (vendored at
    ``tests/fixtures/junit-xml/JUnit.xsd``) requires every
    attribute set here AND requires ``<properties>``,
    ``<system-out>``, and ``<system-err>`` child elements (each
    minOccurs=1). This helper seeds those three elements as
    empty placeholders so the suite is xsd-valid even before
    callers add testcases. The element order — properties,
    testcases, system-out, system-err — matches the xsd's
    sequence; callers add testcases via :func:`add_testcase`
    (which inserts before system-out) or by direct tree
    manipulation.

    Args:
        name: Suite identifier; rendered in CI dashboards.
        tests: Total testcase count for the ``tests=`` attribute.
        failures: Failure count.
        errors: Error count.
        timestamp: ISO 8601 datetime without timezone (the xsd's
            pattern excludes timezone offsets). Default is
            :data:`DETERMINISTIC_TIMESTAMP` for snapshot stability.
        hostname: Host where tests ran. Default ``"localhost"``.
        time: Suite duration in seconds (decimal string). Default
            ``"0"`` since protokit's checks aren't time-budgeted.

    Returns:
        A ``<testsuite>`` element with the required scaffold.
        Attribute order is determined by insertion order on
        Python 3.8+ ``Element.set`` calls, so output is
        deterministic.
    """
    suite = ET.Element("testsuite")
    suite.set("name", xml_safe_text(name))
    suite.set("tests", str(tests))
    suite.set("failures", str(failures))
    suite.set("errors", str(errors))
    # Scrubbed like every other slot: these default to constants
    # today, but they are caller-settable parameters, and the
    # eventual "real values for live CI runs" flag would feed them
    # a machine hostname — a filesystem-adjacent string that can
    # carry surrogates.
    suite.set("timestamp", xml_safe_text(timestamp))
    suite.set("hostname", xml_safe_text(hostname))
    suite.set("time", xml_safe_text(time))
    # Required-by-xsd scaffold. Callers can replace properties
    # via append_properties (which finds and overwrites) and
    # write text into system-out via append_system_out.
    ET.SubElement(suite, "properties")
    sys_out = ET.SubElement(suite, "system-out")
    sys_out.text = ""
    sys_err = ET.SubElement(suite, "system-err")
    sys_err.text = ""
    return suite


def add_testcase(suite: ET.Element, case: ET.Element) -> None:
    """Insert a ``<testcase>`` into a suite at the correct position.

    The xsd requires the order: properties, testcase*, system-out,
    system-err. The :func:`make_testsuite` helper seeds the
    suite with empty properties + system-out + system-err
    placeholders, so testcases must be inserted BEFORE the
    first system-out child to satisfy the schema.

    The scan runs BACKWARDS: system-out/system-err are always the
    last two children (nothing is ever appended after them), so the
    target is one step from the tail. A forward scan would rescan
    every already-inserted testcase, making suite construction
    quadratic — 20k cases took ~4.5s.
    """
    sys_out_index = None
    for i in range(len(suite) - 1, -1, -1):
        if suite[i].tag == "system-out":
            sys_out_index = i
            break
    if sys_out_index is None:
        suite.append(case)
    else:
        suite.insert(sys_out_index, case)


def make_testcase(
    *,
    classname: str,
    name: str,
    time: str = "0",
) -> ET.Element:
    """Construct a ``<testcase>`` with all xsd-required attrs.

    Args:
        classname: ``classname=`` attribute (rule_id, commit
            short SHA, or a fixed string like ``"compat"`` /
            ``"diff"`` for synthetic cases).
        name: ``name=`` attribute (typically the finding path
            or commit subject).
        time: Test duration in seconds. Default ``"0"``.

    Returns:
        A ``<testcase>`` element ready to receive a child
        ``<failure>``, ``<error>``, or ``<skipped>``.
    """
    case = ET.Element("testcase")
    case.set("classname", xml_safe_text(classname))
    case.set("name", xml_safe_text(name))
    case.set("time", xml_safe_text(time))
    return case


def append_failure(
    case: ET.Element, *, message: str, type_: str, body: str | None = None,
) -> None:
    """Attach a ``<failure>`` child element to a testcase.

    Args:
        case: The ``<testcase>`` element to mark as failed.
        message: Short summary for the ``message=`` attribute.
        type_: Required ``type=`` attribute (e.g., severity tag).
        body: Optional longer text content (multi-line
            details). Scrubbed for XML-forbidden control chars.
    """
    failure = ET.SubElement(case, "failure")
    failure.set("message", xml_safe_text(message))
    failure.set("type", xml_safe_text(type_))
    if body is not None:
        failure.text = xml_safe_text(body)


def append_error(
    case: ET.Element, *, message: str, type_: str, body: str | None = None,
) -> None:
    """Attach an ``<error>`` child element to a testcase."""
    error = ET.SubElement(case, "error")
    error.set("message", xml_safe_text(message))
    error.set("type", xml_safe_text(type_))
    if body is not None:
        error.text = xml_safe_text(body)


def append_system_out(suite: ET.Element, text: str) -> None:
    """Set the suite's ``<system-out>`` text content (scrubbed).

    :func:`make_testsuite` already seeds an empty ``<system-out>``
    element to satisfy the xsd; this function fills its text
    rather than appending a duplicate (the xsd allows only one).
    """
    sys_out = suite.find("system-out")
    if sys_out is None:
        sys_out = ET.SubElement(suite, "system-out")
    sys_out.text = xml_safe_text(text)


def append_properties(suite: ET.Element, props: dict[str, str | None]) -> None:
    """Populate the suite's ``<properties>`` block.

    :func:`make_testsuite` seeds an empty ``<properties>``
    element as the first child to satisfy the xsd; this
    function fills it with ``<property name=... value=.../>``
    children. Each ``(name, value)`` pair becomes one property;
    ``None`` values render as the empty string.
    """
    properties = suite.find("properties")
    if properties is None:
        properties = ET.Element("properties")
        suite.insert(0, properties)
    # Wipe any prior children so the helper is idempotent.
    for child in list(properties):
        properties.remove(child)
    for key, value in props.items():
        prop = ET.SubElement(properties, "property")
        prop.set("name", xml_safe_text(key))
        prop.set("value", xml_safe_text(value if value is not None else ""))


def serialize(root: ET.Element) -> str:
    """Render the element tree as a UTF-8 XML string.

    Always emits the ``<?xml version='1.0' encoding='utf-8'?>``
    prolog. We serialize as bytes (the only mode where
    ElementTree honours ``xml_declaration`` reliably) and then
    decode. ElementTree handles all standard XML escaping;
    control chars must be scrubbed before this call (use
    :func:`xml_safe_text` or one of the ``make_*`` /
    ``append_*`` helpers).
    """
    return ET.tostring(root, xml_declaration=True, encoding="utf-8").decode("utf-8")
