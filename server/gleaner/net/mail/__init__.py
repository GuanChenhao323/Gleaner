"""自研邮件协议客户端：SMTP（STARTTLS）、IMAP（IDLE）、POP3。"""

from .base import MailError
from .imap import IMAPClient, MailboxInfo
from .mime import ParsedMail, parse_mail
from .pop3 import POP3Client
from .smtp import (
    Attachment,
    OutgoingMail,
    SMTPClient,
    SMTPResult,
    build_message,
    dot_stuff,
    send_with_retry,
)

__all__ = [
    "Attachment",
    "IMAPClient",
    "MailError",
    "MailboxInfo",
    "OutgoingMail",
    "POP3Client",
    "ParsedMail",
    "SMTPClient",
    "SMTPResult",
    "build_message",
    "dot_stuff",
    "parse_mail",
    "send_with_retry",
]
