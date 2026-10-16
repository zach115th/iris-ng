"""Read an uploaded working-timeline CSV that may be gzip-compressed.

The import modal compresses large files in the browser before sending them
(a full-host Hayabusa run is ~1 GB of text and gzips ~40x, and on a remote
link the upload is most of the wait), and a script may POST a ``.csv.gz``.
Detection is by the two gzip magic bytes, never by the file name or the
content type, so every import endpoint takes either form.

Decompression is lazy: the parsers read the returned stream row by row, so a
small upload that inflates to gigabytes costs CPU only up to the parser's
event cap. The one in-memory consumer (the master-timeline CSV parser) goes
through ``read_upload_bytes`` with an explicit size limit.
"""
from __future__ import annotations

import gzip
import io
import zlib
from typing import BinaryIO

GZIP_MAGIC = b'\x1f\x8b'
_CHUNK = 1 << 20


class UploadDecodeError(Exception):
    """The upload is gzip but damaged, truncated, or larger than allowed."""


class _Prefixed(io.RawIOBase):
    """Serve the bytes already read for detection, then the rest of the stream."""

    def __init__(self, head: bytes, rest):
        self._head = head
        self._rest = rest

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        if self._head:
            n = min(len(b), len(self._head))
            b[:n] = self._head[:n]
            self._head = self._head[n:]
            return n
        data = self._rest.read(len(b))
        n = len(data)
        b[:n] = data
        return n


class _GuardedGzip(io.RawIOBase):
    """Turn a damaged or truncated gzip body into UploadDecodeError (a 400),
    instead of the EOFError / BadGzipFile / zlib.error that would surface
    from inside the CSV reader as a 500."""

    def __init__(self, gz: gzip.GzipFile):
        self._gz = gz

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        try:
            return self._gz.readinto(b)
        except (EOFError, OSError, zlib.error) as exc:
            raise UploadDecodeError(
                f'The compressed upload is damaged or incomplete ({exc}).'
            ) from exc


def open_upload(stream) -> BinaryIO | None:
    """Return a binary stream of the uploaded CSV bytes, gunzipping when the
    upload starts with the gzip magic. ``None`` for an empty upload."""
    head = b''
    while len(head) < len(GZIP_MAGIC):
        more = stream.read(len(GZIP_MAGIC) - len(head))
        if not more:
            break
        head += more
    if not head:
        return None
    raw = io.BufferedReader(_Prefixed(head, stream), _CHUNK)
    if head == GZIP_MAGIC:
        return io.BufferedReader(_GuardedGzip(gzip.GzipFile(fileobj=raw, mode='rb')), _CHUNK)
    return raw


def read_upload_bytes(stream, limit: int) -> bytes | None:
    """``open_upload`` read into memory, refusing more than ``limit`` bytes of
    CSV (after decompression). ``None`` for an empty upload."""
    opened = open_upload(stream)
    if opened is None:
        return None
    data = opened.read(limit + 1)
    if len(data) > limit:
        raise UploadDecodeError(
            f'The CSV is larger than {limit // (1024 * 1024)} MB once decompressed; '
            'split it or narrow the export.'
        )
    return data
