import socketserver
import threading
from email.parser import BytesParser
from email.policy import default
from uuid import uuid4

import pytest

from app.core.agent_tools import AgentFailure
from app.core.config import Settings
from app.workers.agents import deliver


def test_actual_local_smtp_preserves_recipient_unicode_and_message_id():
    captured = []

    class SMTP(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(5)
            self.wfile.write(b"220 localhost synthetic test\r\n")
            while line := self.rfile.readline():
                command = line.split(b" ", 1)[0].strip().upper()
                if command in {b"EHLO", b"HELO", b"MAIL", b"RCPT", b"RSET"}:
                    self.wfile.write(b"250 OK\r\n")
                elif command == b"DATA":
                    self.wfile.write(b"354 End with dot\r\n")
                    chunks = []
                    while (part := self.rfile.readline()) != b".\r\n":
                        if not part:
                            return
                        chunks.append(part)
                    captured.append(b"".join(chunks))
                    self.wfile.write(b"250 Captured\r\n")
                elif command == b"QUIT":
                    self.wfile.write(b"221 Bye\r\n")
                    return

    with socketserver.TCPServer(("127.0.0.1", 0), SMTP) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        mid = uuid4()
        try:
            deliver(
                {
                    "id": mid,
                    "recipient": "synthetic@example.com",
                    "subject": "AgentHire — سؤال تکمیلی",
                    "body": "Docker experience?\nاین پیام فقط آزمایشی است.",
                },
                Settings(
                    _env_file=None,
                    agent_mail_host="127.0.0.1",
                    agent_mail_port=server.server_address[1],
                ),
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)
    message = BytesParser(policy=default).parsebytes(captured[0])
    assert (
        message["To"] == "synthetic@example.com"
        and message["Message-ID"] == f"<{mid}@agenthire.test>"
    )
    assert (
        "سؤال تکمیلی" in message["Subject"] and "فقط آزمایشی" in message.get_content()
    )


def test_external_smtp_relay_is_refused():
    with pytest.raises(AgentFailure, match="SMTP_HOST_BLOCKED"):
        deliver(
            {},
            Settings(_env_file=None).model_copy(
                update={"agent_mail_host": "external.example.com"}
            ),
        )
