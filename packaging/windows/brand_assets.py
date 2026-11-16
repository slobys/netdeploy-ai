"""Rebuild the shared vector mark and antialiased Windows icons, without dependencies."""
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = ROOT / "app/static/brand"
GREEN = (12, 101, 81)
WHITE = (244, 255, 251)
MINT = (115, 229, 177)
ROUTE = [(14, 47), (14, 17), (22, 17), (40, 37), (40, 27),
         (48, 27), (48, 47), (40, 47), (22, 27), (22, 47)]
SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-labelledby="title desc">
  <title id="title">NetDeploy AI</title>
  <desc id="desc">An N-shaped network route ending at a mint deployment node.</desc>
  <rect width="64" height="64" rx="15" fill="#0c6551"/>
  <path d="M14 47V17H22L40 37V27H48V47H40L22 27V47Z" fill="#f4fffb"/>
  <circle cx="44" cy="17" r="5" fill="#73e5b1"/>
</svg>
'''


def in_route(x, y):
    inside = False
    a, b = ROUTE[-1]
    for c, d in ROUTE:
        if (b > y) != (d > y) and x < (c - a) * (y - b) / (d - b) + a:
            inside = not inside
        a, b = c, d
    return inside


def sample(x, y):
    dx, dy = max(abs(x - 32) - 17, 0), max(abs(y - 32) - 17, 0)
    if dx * dx + dy * dy > 15 * 15:
        return None
    if (x - 44) ** 2 + (y - 17) ** 2 <= 25:
        return MINT
    return WHITE if in_route(x, y) else GREEN


def png(size):
    rows = bytearray()
    scale = 64 / size
    offsets = (.125, .375, .625, .875)
    for y in range(size):
        rows.append(0)
        for x in range(size):
            colors = [color for oy in offsets for ox in offsets
                      if (color := sample((x + ox) * scale, (y + oy) * scale)) is not None]
            count = len(colors)
            rows.extend((*[round(sum(c[i] for c in colors) / count) if count else 0 for i in range(3)],
                         round(255 * count / 16)))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))

    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>2I5B', size, size, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(rows))) + chunk(b'IEND', b''))


def build():
    DESTINATION.mkdir(parents=True, exist_ok=True)
    (DESTINATION / 'logo.svg').write_text(SVG, encoding='utf-8')
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = {size: png(size) for size in sizes + [192, 512]}
    for size in [64, 128, 192, 512]:
        (DESTINATION / f'icon-{size}.png').write_bytes(images[size])
    offset = 6 + 16 * len(sizes)
    entries = bytearray()
    for size in sizes:
        data = images[size]
        entries.extend(struct.pack('<4B2H2I', size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    (DESTINATION / 'favicon.ico').write_bytes(struct.pack('<3H', 0, 1, len(sizes)) + entries
                                             + b''.join(images[size] for size in sizes))
    print('Shared NetDeploy mark rebuilt: SVG, PNG and 7 Windows icon sizes.')


if __name__ == '__main__':
    build()
