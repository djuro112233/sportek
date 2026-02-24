import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFilter
import os

np.random.seed(42)

# ─── DIO 1: defect_log.csv ───────────────────────────────────────────────────

prod = pd.read_csv('data/production/production_log.csv')
prod_with_defects = prod[prod['defect_qty'] > 0].copy()

INSPECTORS = [f'INS_{i:02d}' for i in range(1, 16)]

DEFECT_TYPES = [
    'šav neravnomjeran',
    'ljepilo vidljivo',
    'boja odstupa',
    'materijal oštećen',
    'dimenzija van tolerancije',
    '3D knit greška',
    'logo pozicija',
    'đon delaminacija',
]
DEFECT_PROBS = [0.22, 0.18, 0.14, 0.12, 0.10, 0.09, 0.08, 0.07]

# Severity distribution per defect type: [critical, major, minor]
SEVERITY_MAP = {
    'šav neravnomjeran':        [0.10, 0.45, 0.45],
    'ljepilo vidljivo':         [0.08, 0.42, 0.50],
    'boja odstupa':             [0.12, 0.48, 0.40],
    'materijal oštećen':        [0.20, 0.50, 0.30],
    'dimenzija van tolerancije': [0.25, 0.50, 0.25],
    '3D knit greška':           [0.15, 0.50, 0.35],
    'logo pozicija':            [0.05, 0.35, 0.60],
    'đon delaminacija':         [0.40, 0.40, 0.20],
}

SEVERITIES = ['critical', 'major', 'minor']

# Action probabilities per severity: [scrap, rework, pass]
ACTION_MAP = {
    'critical': [0.90, 0.10, 0.00],
    'major':    [0.30, 0.60, 0.10],
    'minor':    [0.05, 0.20, 0.75],
}
ACTIONS = ['scrap', 'rework', 'pass']

DETECTION_POINTS = ['incoming', 'inline', 'final', 'customer_return']
DETECTION_PROBS = [0.08, 0.35, 0.50, 0.07]

TARGET = 5000


def generate_defect_rows():
    rows = []
    for _, prow in prod_with_defects.iterrows():
        n = int(prow['defect_qty'])
        for _ in range(n):
            defect_type = np.random.choice(DEFECT_TYPES, p=DEFECT_PROBS)
            sev_probs = SEVERITY_MAP[defect_type]
            severity = np.random.choice(SEVERITIES, p=sev_probs)
            action = np.random.choice(ACTIONS, p=ACTION_MAP[severity])
            detection = np.random.choice(DETECTION_POINTS, p=DETECTION_PROBS)
            insp_time = max(int(np.random.normal(45, 12)), 10)
            photo = np.random.random() < 0.60

            rows.append({
                'date': prow['date'],
                'line_id': prow['line_id'],
                'brand': prow['brand'],
                'model_name': prow['model_name'],
                'inspector_id': np.random.choice(INSPECTORS),
                'defect_type': defect_type,
                'severity': severity,
                'action': action,
                'detection_point': detection,
                'inspection_time_seconds': insp_time,
                'photo_taken': photo,
            })
    return rows


print("Generating defect log from production data...")
all_rows = generate_defect_rows()
print(f"  Raw defect records from production: {len(all_rows):,}")

df = pd.DataFrame(all_rows)

if len(df) > TARGET:
    df = df.sample(n=TARGET, random_state=42).reset_index(drop=True)
elif len(df) < TARGET:
    shortfall = TARGET - len(df)
    extra = df.sample(n=shortfall, replace=True, random_state=42).reset_index(drop=True)
    df = pd.concat([df, extra], ignore_index=True)

df.to_csv('data/quality/defect_log.csv', index=False)
print(f"  Saved defect_log.csv: {len(df):,} rows")


# ─── DIO 2: defect images (50 PNGs, 200x200) ────────────────────────────────

IMG_DIR = 'data/quality/defect_images'
SIZE = 200


def make_base_texture(rng):
    """Weave pattern simulating fabric."""
    arr = rng.integers(170, 181, size=(SIZE, SIZE, 3), dtype=np.uint8)
    # Horizontal weave lines every 4px
    for y in range(0, SIZE, 4):
        arr[y, :, :] = np.clip(arr[y, :, :].astype(int) - 15, 0, 255).astype(np.uint8)
    # Vertical weave lines every 4px
    for x in range(0, SIZE, 4):
        arr[:, x, :] = np.clip(arr[:, x, :].astype(int) - 10, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    img = img.filter(ImageFilter.GaussianBlur(radius=0.8))
    return img


def add_scratch(img, rng):
    draw = ImageDraw.Draw(img)
    x1, y1 = rng.integers(10, 100), rng.integers(10, 80)
    x2, y2 = rng.integers(100, 190), rng.integers(120, 190)
    width = rng.integers(1, 4)
    r, g, b = rng.integers(60, 110), rng.integers(40, 80), rng.integers(40, 80)
    draw.line([(x1, y1), (x2, y2)], fill=(int(r), int(g), int(b)), width=int(width))
    return img


def add_stain(img, rng):
    draw = ImageDraw.Draw(img)
    cx, cy = rng.integers(40, 160), rng.integers(40, 160)
    rx, ry = rng.integers(15, 40), rng.integers(15, 40)
    r, g, b = rng.integers(100, 145), rng.integers(80, 120), rng.integers(60, 100)
    draw.ellipse([int(cx-rx), int(cy-ry), int(cx+rx), int(cy+ry)],
                 fill=(int(r), int(g), int(b), 160))
    return img


def add_hole(img, rng):
    draw = ImageDraw.Draw(img)
    cx, cy = rng.integers(50, 150), rng.integers(50, 150)
    rx, ry = rng.integers(8, 20), rng.integers(8, 20)
    draw.ellipse([int(cx-rx), int(cy-ry), int(cx+rx), int(cy+ry)],
                 fill=(int(rng.integers(30, 60)), int(rng.integers(30, 60)), int(rng.integers(30, 60))))
    return img


def add_glue(img, rng):
    draw = ImageDraw.Draw(img)
    n_blobs = rng.integers(4, 10)
    for _ in range(n_blobs):
        cx, cy = rng.integers(20, 180), rng.integers(20, 180)
        rx, ry = rng.integers(3, 10), rng.integers(3, 10)
        v = rng.integers(210, 245)
        draw.ellipse([int(cx-rx), int(cy-ry), int(cx+rx), int(cy+ry)],
                     fill=(int(v), int(v), int(v-10), 180))
    return img


DEFECT_FUNCS = [add_scratch, add_stain, add_hole, add_glue]

print("\nGenerating defect images...")
rng = np.random.default_rng(42)
img_count = 0

# 25 defect images
for i in range(1, 26):
    img = make_base_texture(rng)
    img = img.convert('RGBA')
    func = DEFECT_FUNCS[rng.integers(0, len(DEFECT_FUNCS))]
    img = func(img, rng)
    img = img.convert('RGB')
    img.save(os.path.join(IMG_DIR, f'defect_{i:03d}.png'))
    img_count += 1

# 25 OK images
for i in range(1, 26):
    img = make_base_texture(rng)
    img.save(os.path.join(IMG_DIR, f'ok_{i:03d}.png'))
    img_count += 1

print(f"  Saved {img_count} images to {IMG_DIR}/")

# ─── Summary ─────────────────────────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"SUMMARY")
print(f"{'='*50}")
print(f"Defect log rows:  {len(df):,}")
print(f"Images generated: {img_count}")
print(f"\nTop 3 defect types:")
top3 = df['defect_type'].value_counts().head(3)
for dtype, count in top3.items():
    pct = count / len(df) * 100
    print(f"  {dtype:30s} {count:>5,} ({pct:.1f}%)")
print(f"\nSeverity distribution:")
for sev, count in df['severity'].value_counts().items():
    print(f"  {sev:10s} {count:>5,} ({count/len(df)*100:.1f}%)")
print(f"\nAction distribution:")
for act, count in df['action'].value_counts().items():
    print(f"  {act:10s} {count:>5,} ({count/len(df)*100:.1f}%)")
