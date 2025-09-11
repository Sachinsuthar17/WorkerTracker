"""Utility functions for generating QR codes for workers and bundles.

This module centralises QR code generation to avoid duplication across
different parts of the application.  The functions will create directories
as needed and return the file paths of the generated images.  QR codes
encode simple strings (e.g. token IDs or bundle payloads) so that the
ESP32 scanners can decode them easily.
"""

import os
import qrcode


def ensure_dir(path: str) -> str:
    """Ensure that ``path`` exists.

    ``os.makedirs`` with ``exist_ok=True`` will create intermediate
    directories as required.  Returns the input path for convenience.
    """

    os.makedirs(path, exist_ok=True)
    return path


def make_worker_qr(static_dir: str, token_id: str, filename: str) -> str:
    """Generate a QR code for a worker.

    The ``token_id`` is encoded directly into the QR code.  The file is
    written into ``static_dir`` and named according to ``filename``.
    """

    ensure_dir(static_dir)
    img = qrcode.make(token_id)
    fp = os.path.join(static_dir, filename)
    img.save(fp)
    return fp


def make_bundle_qr(static_dir: str, payload: str, filename: str) -> str:
    """Generate a QR code for a bundle.

    The payload is typically a pipe-delimited string containing the bundle
    identifier and other metadata.  Storing additional fields in the QR
    allows future expansion without changing the schema.  The generated
    image is saved and the file path returned.
    """

    ensure_dir(static_dir)
    img = qrcode.make(payload)
    fp = os.path.join(static_dir, filename)
    img.save(fp)
    return fp