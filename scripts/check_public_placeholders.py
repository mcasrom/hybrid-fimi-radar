from pathlib import Path
import sys
root = Path('/home/miguelc/fimi_local/web')
bad = ('[PENDIENTE', '__VERSION_GENERADA__')
hits = []
for p in sorted(root.rglob('*')):
    if p.suffix.lower() not in ('.html', '.xml'):
        continue
    txt = p.read_text(encoding='utf-8', errors='replace')
    for marker in bad:
        if marker in txt:
            hits.append(f'{p}: {marker}')
if hits:
    print('\n'.join(hits))
    sys.exit(1)
print('OK: sin placeholders públicos')
