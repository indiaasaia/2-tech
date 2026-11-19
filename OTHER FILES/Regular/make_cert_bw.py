import io, zlib, json, base64, hashlib
import pypdfium2 as pdfium
from PIL import Image

SRC = 'certificate_of_enrolment_small.pdf'
OUT = 'certificate_of_enrolment_bw.pdf'
DPI = 130

pdf = pdfium.PdfDocument(SRC)
images = []
for page in pdf:
    bmp = page.render(scale=DPI / 72)
    pil = bmp.to_pil().convert('1')  # 1-bit
    images.append(pil)

W, H = images[0].size
print('rendered', W, 'x', H, 'pages:', len(images))

# Pack 1-bit rows (PIL '1' tobytes gives packed rows padded to byte boundary)
raw_images = []
for im in images:
    if im.size != (W, H):
        im = im.resize((W, H))
    data = im.tobytes()  # packed, rows padded
    stride = (W + 7) // 8
    assert len(data) == stride * H, (len(data), stride * H)
    comp = zlib.compress(data, 9)
    raw_images.append(comp)
    print('image compressed:', len(comp))

def build_pdf(img_streams):
    objs = {}
    n_pages = len(img_streams)
    # 1: catalog, 2: pages, then per page: content stream, image xobject, page obj
    page_ids = []
    next_id = 3
    entries = []
    for i, comp in enumerate(img_streams):
        content_id = next_id; next_id += 1
        image_id = next_id; next_id += 1
        page_id = next_id; next_id += 1
        entries.append((content_id, image_id, page_id))
    pages_id = 2
    kids = ' '.join(f'{p} 0 R' for (_, _, p) in entries)
    objs[1] = b'<< /Type /Catalog /Pages 2 0 R >>'
    objs[2] = f'<< /Type /Pages /Count {n_pages} /Kids [ {kids} ] >>'.encode()
    for i, (content_id, image_id, page_id) in enumerate(entries):
        stride = (W + 7) // 8
        content = f'q {W} 0 0 {H} 0 0 cm /Im0 Do Q'.encode()
        objs[content_id] = (f'<< /Length {len(content)} >>\nstream\n'.encode() + content + b'\nendstream')
        head = (f'<< /Type /XObject /Subtype /Image /Width {W} /Height {H} '
                f'/ColorSpace /DeviceGray /BitsPerComponent 1 /Filter /FlateDecode '
                f'/Length {len(img_streams[i])} >>').encode()
        objs[image_id] = head + b'\nstream\n' + img_streams[i] + b'\nendstream'
        objs[page_id] = (f'<< /Type /Page /Parent 2 0 R /MediaBox [ 0 0 {W * 72 / DPI:.2f} {H * 72 / DPI:.2f} ] '
                         f'/Resources << /XObject << /Im0 {image_id} 0 R >> /ProcSet [ /PDF /ImageB ] >> '
                         f'/Contents {content_id} 0 R >>').encode()
    out = io.BytesIO()
    out.write(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = {}
    for oid in sorted(objs):
        offsets[oid] = out.tell()
        out.write(f'{oid} 0 obj\n'.encode())
        out.write(objs[oid])
        out.write(b'\nendobj\n')
    xref_pos = out.tell()
    maxid = max(objs)
    out.write(f'xref\n0 {maxid + 1}\n'.encode())
    out.write(b'0000000000 65535 f \n')
    for oid in range(1, maxid + 1):
        out.write(f'{offsets[oid]:010d} 00000 n \n'.encode())
    out.write(f'trailer\n<< /Size {maxid + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n'.encode())
    return out.getvalue()

pdf_bytes = build_pdf(raw_images)
open(OUT, 'wb').write(pdf_bytes)
print('PDF written:', OUT, len(pdf_bytes), 'bytes')

b64 = base64.b64encode(pdf_bytes).decode()
print('b64 chars:', len(b64))
print('sha256:', hashlib.sha256(pdf_bytes).hexdigest())

CHUNK = 4000
n = (len(b64) + CHUNK - 1) // CHUNK
meta = {'sha256': hashlib.sha256(pdf_bytes).hexdigest(), 'b64len': len(b64), 'chunks': []}
for i in range(n):
    c = b64[i * CHUNK:(i + 1) * CHUNK]
    fn = f'bw_{i}.txt'
    open(fn, 'w', newline='').write(c)
    h = hashlib.sha256(c.encode()).hexdigest()
    meta['chunks'].append({'file': fn, 'len': len(c), 'sha256': h})
    print(fn, len(c), h[:16])
json.dump(meta, open('bwmeta.json', 'w'), indent=1)
print('chunks:', n)
