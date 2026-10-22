"""自研 DNS 解析器（RFC 1035）。"""

from .resolver import (
    TYPE_A,
    TYPE_AAAA,
    TYPE_CNAME,
    DNSError,
    DNSMessage,
    Record,
    Resolver,
    decode_message,
    encode_name,
    encode_query,
)

__all__ = [
    "TYPE_A",
    "TYPE_AAAA",
    "TYPE_CNAME",
    "DNSError",
    "DNSMessage",
    "Record",
    "Resolver",
    "decode_message",
    "encode_name",
    "encode_query",
]
