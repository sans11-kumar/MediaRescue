"""Conservative contiguous-file signature scanner. Never writes to the source."""
from __future__ import annotations
from dataclasses import dataclass
import os, struct, zlib

CHUNK = 2 * 1024 * 1024
MAX_PHOTO = 150 * 1024 * 1024
MAX_VIDEO = 4 * 1024 * 1024 * 1024

@dataclass(frozen=True)
class Hit:
    offset: int
    length: int
    kind: str
    extension: str
    note: str


def _read(f, at, count):
    f.seek(at)
    return f.read(count)


def jpeg_length(f, at, limit):
    if _read(f, at, 3) != b'\xff\xd8\xff':
        return None
    # Conservative EOI detection; fragments may produce false positives.
    end = min(limit, at + MAX_PHOTO)
    pos = at + 3
    tail = b''
    while pos < end:
        data = _read(f, pos, min(CHUNK, end - pos))
        if not data: break
        pair = (tail + data).find(b'\xff\xd9')
        if pair != -1:
            length = pos - len(tail) + pair + 2 - at
            return length if length >= 100 else None
        tail = data[-1:]
        pos += len(data)
    return None


def png_length(f, at, limit):
    if _read(f, at, 8) != b'\x89PNG\r\n\x1a\n': return None
    pos = at + 8
    end = min(limit, at + MAX_PHOTO)
    saw_ihdr = False
    while pos + 12 <= end:
        head = _read(f, pos, 8)
        if len(head) != 8: return None
        n, typ = struct.unpack('>I4s', head)
        if n > MAX_PHOTO or pos + 12 + n > end: return None
        if not saw_ihdr:
            if typ != b'IHDR' or n != 13: return None
            saw_ihdr = True
        if not all((65 <= c <= 90) or (97 <= c <= 122) for c in typ): return None
        if typ == b'IEND':
            if n != 0: return None
            return pos + 12 - at
        pos += n + 12
    return None


def mp4_length(f, at, limit):
    """Recognize a contiguous ISO-BMFF stream starting at a valid ftyp box."""
    head = _read(f, at, 16)
    if len(head) != 16 or head[4:8] != b'ftyp': return None
    first_size = int.from_bytes(head[:4], 'big')
    if first_size < 16 or first_size > 4096 or first_size % 4: return None
    pos = at
    maximum = min(limit, at + MAX_VIDEO)
    boxes = 0; has_media = False
    while pos + 8 <= maximum:
        h = _read(f, pos, 16)
        if len(h) < 8: break
        size = int.from_bytes(h[:4], 'big'); typ = h[4:8]
        header = 8
        if size == 1:
            if len(h) < 16: break
            size = int.from_bytes(h[8:16], 'big'); header = 16
        if size == 0:
            # An unbounded final box cannot safely identify EOF.
            break
        if size < header or pos + size > maximum: break
        if typ not in (b'ftyp', b'free', b'skip', b'wide', b'moov', b'mdat', b'uuid', b'meta', b'sidx', b'moof', b'mfra', b'prft', b'styp', b'pdin'):
            break
        if boxes == 0 and typ != b'ftyp': return None
        if typ in (b'mdat', b'moov'): has_media = True
        boxes += 1
        pos += size
        if boxes > 20000: break
    if boxes >= 2 and has_media and pos - at >= 1024:
        brand = head[8:12]
        ext = 'mov' if brand == b'qt  ' else 'mp4'
        return pos - at, ext
    return None


def scan(source, total, stop, report, max_hits=10000):
    """Generator of candidate offsets. File sizes need later validation."""
    signatures = ((b'\xff\xd8\xff', 'jpg'), (b'\x89PNG\r\n\x1a\n', 'png'), (b'ftyp', 'bmff'))
    seen = set()
    with open(source, 'rb', buffering=0) as f:
        offset = 0; carry = b''
        while offset < total and not stop.is_set():
            block = f.read(min(CHUNK, total - offset))
            if not block: break
            buf = carry + block
            base = offset - len(carry)
            for sig, kind in signatures:
                start = 0
                while not stop.is_set():
                    idx = buf.find(sig, start)
                    if idx < 0: break
                    start = idx + 1
                    at = base + idx - (4 if kind == 'bmff' else 0)
                    if at < 0 or at in seen: continue
                    seen.add(at)
                    if kind == 'jpg': length = jpeg_length(f, at, total); ext='jpg'
                    elif kind == 'png': length = png_length(f, at, total); ext='png'
                    else:
                        result = mp4_length(f, at, total)
                        length, ext = result if result else (None, 'mp4')
                    if length:
                        yield Hit(at, length, 'Video' if kind == 'bmff' else 'Photo', ext,
                                  'Signature candidate; contiguous data only')
                        if len(seen) >= max_hits: return
            offset += len(block)
            carry = buf[-32:]
            f.seek(offset)
            report(offset, total)


def copy_hit(source, hit, destination, stop=None):
    """Copy bounded bytes without touching the source. Partial outputs are removed."""
    if os.path.exists(destination): raise FileExistsError(destination)
    try:
        with open(source, 'rb', buffering=0) as src, open(destination, 'xb') as dst:
            src.seek(hit.offset)
            remaining = hit.length
            while remaining:
                if stop is not None and stop.is_set(): raise InterruptedError('Canceled')
                buf = src.read(min(CHUNK, remaining))
                if not buf: raise EOFError('Source became unavailable')
                dst.write(buf)
                remaining -= len(buf)
    except BaseException:
        try: os.remove(destination)
        except OSError: pass
        raise
