"""Isolated, bounded PDF-to-text worker; stdout contains only extracted text."""

import io
import logging
import sys


def main():
    try:
        if sys.platform != "win32":
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        from pypdf import PdfReader

        logging.disable(logging.CRITICAL)
        content = sys.stdin.buffer.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            return 1
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 50:
            return 1
        text = ""
        for page in reader.pages:
            text += (page.extract_text() or "") + "\n"
            if len(text.encode("utf-8")) > 10 * 1024 * 1024:
                return 1
        if not text.strip() or "\0" in text:
            return 1
        sys.stdout.buffer.write(text.encode("utf-8"))
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
