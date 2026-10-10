"""Read a member of a remote ZIP over HTTP range requests, without downloading the archive.

Zenodo's API URLs honour Range, so the central directory can be read from the tail and only the
wanted members fetched. Python's zipfile handles ZIP64 and the directory parsing itself, given a
seekable file object.
"""
import io, sys, time, zipfile, urllib.error, urllib.request

UA={'User-Agent':'fieldwork-validation-lab/0.1 (+https://github.com/digital-twin-ph)'}

def _fetch(url, headers, attempts=6):
    """Zenodo returns intermittent 504s; retry transient failures with backoff."""
    last=None
    for attempt in range(attempts):
        try:
            req=urllib.request.Request(url, headers={**UA, **headers})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read(), r.headers
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            code=getattr(error,'code',None)
            if code is not None and code not in (500,502,503,504,429): raise
            last=error; time.sleep(2*(attempt+1))
    raise RuntimeError(f'{url} failed after {attempts} attempts: {last}')

class HttpRangeFile(io.RawIOBase):
    def __init__(self, url, chunk=1 << 20):
        self.url, self._pos, self._chunk = url, 0, chunk
        _, headers = _fetch(url, {'Range': 'bytes=0-0'})
        self.size = int(headers['content-range'].split('/')[1])
        self.requests = self.bytes_read = 0
    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self._pos
    def seek(self, offset, whence=0):
        self._pos = offset if whence == 0 else self._pos + offset if whence == 1 else self.size + offset
        return self._pos
    def read(self, n=-1):
        if n is None or n < 0: n = self.size - self._pos
        if n == 0 or self._pos >= self.size: return b''
        end = min(self._pos + n, self.size) - 1
        data, _ = _fetch(self.url, {'Range': f'bytes={self._pos}-{end}'})
        self.requests += 1; self.bytes_read += len(data); self._pos += len(data)
        return data
    def readinto(self, b):
        data = self.read(len(b)); b[:len(data)] = data; return len(data)

def open_remote_zip(url):
    return zipfile.ZipFile(io.BufferedReader(HttpRangeFile(url), buffer_size=1 << 20))

if __name__ == '__main__':
    url = sys.argv[1]
    pattern = sys.argv[2] if len(sys.argv) > 2 else ''
    z = open_remote_zip(url)
    names = [n for n in z.namelist() if pattern in n]
    print(f'archive members: {len(z.namelist())}  matching "{pattern}": {len(names)}')
    for n in names[:40]:
        info = z.getinfo(n)
        print(f'  {info.file_size/1e6:9.2f} MB  {n}')
    if len(names) > 40: print(f'  ... and {len(names)-40} more')

def extract_member(url, member, out_path):
    """Stream one member out of a remote zip to a local file."""
    z = open_remote_zip(url)
    info = z.getinfo(member)
    with z.open(info) as src, open(out_path, 'wb') as dst:
        while chunk := src.read(1 << 20): dst.write(chunk)
    return info.file_size

def extract_member_fast(url, member, out_path, zinfo=None):
    """Fetch one member's compressed bytes in a single range request and inflate locally.

    Streaming through zipfile issues one request per buffer, which Zenodo's latency makes slow.
    A deflated member can instead be pulled whole in one GET and inflated here.
    """
    import struct, zlib
    info = zinfo or open_remote_zip(url).getinfo(member)
    head, _ = _fetch(url, {'Range': f'bytes={info.header_offset}-{info.header_offset+29}'})
    signature, = struct.unpack('<I', head[:4])
    if signature != 0x04034b50: raise RuntimeError('not a local file header')
    name_len, extra_len = struct.unpack('<HH', head[26:30])
    start = info.header_offset + 30 + name_len + extra_len
    raw, _ = _fetch(url, {'Range': f'bytes={start}-{start+info.compress_size-1}'})
    if len(raw) != info.compress_size:
        raise RuntimeError(f'short read: {len(raw)} of {info.compress_size}')
    data = zlib.decompressobj(-15).decompress(raw) if info.compress_type == 8 else raw
    if len(data) != info.file_size:
        raise RuntimeError(f'inflated to {len(data)}, expected {info.file_size}')
    with open(out_path, 'wb') as fh: fh.write(data)
    return len(data)
