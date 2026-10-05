"""A proto2 schema and payloads that put a non-UTF-8 string at every depth.

upb does not check UTF-8 in a proto2 ``string`` field and hands the value back
as ``bytes``; pure-Python rejects it while parsing. The payload seams
(``protokit diff``, storage scans, ``forensics match``) walk a parsed message
so both backends reach the same verdict. These payloads put the bad string
somewhere the walk has to reach: top level, a nested message, a repeated
field, a map key, a map value, a set extension and a group.

The payloads are hand-encoded: neither backend lets a caller set a non-UTF-8
string, so there is no message to serialize.
"""

from __future__ import annotations

from google.protobuf import descriptor_pb2

_F = descriptor_pb2.FieldDescriptorProto
_OPT, _REP = _F.LABEL_OPTIONAL, _F.LABEL_REPEATED

TYPE_NAME = "u.M"
BAD = b"\xff\xfe"


def schema() -> descriptor_pb2.FileDescriptorSet:
    """``u.M``: every place a proto2 string can sit, plus an int for a clean record."""
    fdp = descriptor_pb2.FileDescriptorProto(name="u.proto", package="u", syntax="proto2")
    inner = fdp.message_type.add(name="Inner")
    inner.field.add(name="s", number=1, type=_F.TYPE_STRING, label=_OPT)
    m = fdp.message_type.add(name="M")
    m.field.add(name="s", number=1, type=_F.TYPE_STRING, label=_OPT)
    m.field.add(name="inner", number=2, type=_F.TYPE_MESSAGE, label=_OPT, type_name=".u.Inner")
    m.field.add(name="tags", number=3, type=_F.TYPE_STRING, label=_REP)
    entry = m.nested_type.add(name="MEntry")
    entry.options.map_entry = True
    entry.field.add(name="key", number=1, type=_F.TYPE_STRING, label=_OPT)
    entry.field.add(name="value", number=2, type=_F.TYPE_STRING, label=_OPT)
    m.field.add(name="m", number=4, type=_F.TYPE_MESSAGE, label=_REP, type_name=".u.M.MEntry")
    group = m.nested_type.add(name="G")
    group.field.add(name="s", number=6, type=_F.TYPE_STRING, label=_OPT)
    m.field.add(name="g", number=5, type=_F.TYPE_GROUP, label=_OPT, type_name=".u.M.G")
    m.field.add(name="n", number=7, type=_F.TYPE_INT32, label=_OPT)
    m.extension_range.add(start=100, end=200)
    fdp.extension.add(
        name="ext", number=100, type=_F.TYPE_STRING, label=_OPT, extendee=".u.M",
    )
    fds = descriptor_pb2.FileDescriptorSet()
    fds.file.append(fdp)
    return fds


def _len(tag: int, body: bytes) -> bytes:
    return bytes([tag, len(body)]) + body


#: A record per location, each holding :data:`BAD` in one string.
BAD_PAYLOADS: dict[str, bytes] = {
    "top": _len(0x0A, BAD),
    "nested": _len(0x12, _len(0x0A, BAD)),
    "repeated": _len(0x1A, b"ok") + _len(0x1A, BAD),
    "map_key": _len(0x22, _len(0x0A, BAD) + _len(0x12, b"v")),
    "map_value": _len(0x22, _len(0x0A, b"k") + _len(0x12, BAD)),
    "group": b"\x2b" + _len(0x32, BAD) + b"\x2c",
    # Field 100, wire type 2: the tag varint is 0xA2 0x06.
    "extension": b"\xa2\x06" + bytes([len(BAD)]) + BAD,
}

#: A record every backend parses: ``n = 7`` and valid strings everywhere.
GOOD = (
    b"\x38\x07"
    + _len(0x0A, b"ok")
    + _len(0x22, _len(0x0A, b"k") + _len(0x12, b"v"))
    + b"\x2b" + _len(0x32, b"ok") + b"\x2c"
    + b"\xa2\x06\x02ok"
)
