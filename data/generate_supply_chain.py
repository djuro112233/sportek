import numpy as np
import pandas as pd
from datetime import datetime, timedelta

np.random.seed(42)
rng = np.random.default_rng(42)

# ─── BASE MATERIALS (30) ─────────────────────────────────────────────────────

BASE_MATERIALS = [
    # Yarn
    ('Flyknit Yarn 2.0 Black', 'Yarn', 'Toray Industries', 'JP', '540233', 18.50, 85),
    ('Flyknit Yarn 2.0 White', 'Yarn', 'Toray Industries', 'JP', '540233', 18.20, 90),
    ('Flyknit Yarn 2.0 Volt', 'Yarn', 'Toray Industries', 'JP', '540233', 19.00, 60),
    # Foam
    ('EVA Foam Sheet 8mm', 'Foam', 'Foam Italia', 'IT', '391590', 4.20, 120),
    ('EVA Foam Sheet 12mm', 'Foam', 'Foam Italia', 'IT', '391590', 5.10, 100),
    # Film
    ('TPU Film Clear 0.3mm', 'Film', 'Covestro AG', 'DE', '392062', 9.00, 55),
    ('TPU Film Matte 0.3mm', 'Film', 'Covestro AG', 'DE', '392062', 9.40, 45),
    # Textile
    ('Polyester Mesh 150D', 'Textile', 'Far Eastern Textile', 'TW', '600632', 3.20, 130),
    ('Polyester Mesh 300D', 'Textile', 'Far Eastern Textile', 'TW', '600632', 3.80, 110),
    # Sole
    ('Rubber Sole Sheet CR', 'Sole', 'Gomma Padana', 'IT', '400599', 12.50, 70),
    ('Rubber Sole Sheet EVA-RB', 'Sole', 'Gomma Padana', 'IT', '400599', 13.80, 65),
    # Composite
    ('Carbon Fiber Plate 1.0mm', 'Composite', 'Toray Composite', 'JP', '681510', 45.00, 20),
    # Adhesive
    ('PU Adhesive PU-400', 'Adhesive', 'Henkel AG', 'DE', '350691', 16.00, 40),
    ('Hot Melt HM-200', 'Adhesive', 'Henkel AG', 'DE', '350691', 22.00, 35),
    # Accessories
    ('Flat Laces 120cm', 'Accessories', 'Zecchetto Accessori', 'IT', '560790', 0.85, 200),
    ('Metal Eyelets 8mm Nickel', 'Accessories', 'Global Trim', 'CN', '830890', 0.12, 500),
    ('NFC Tag NTAG213', 'Accessories', 'NXP Semiconductors', 'NL', '852352', 0.45, 300),
    # Packaging
    ('Shoe Box 310x210 Kraft', 'Packaging', 'Karteks Banja Luka', 'BA', '481910', 0.60, 400),
    ('Tissue Paper White 50x75', 'Packaging', 'Zhejiang Paper', 'CN', '480300', 0.08, 800),
    ('Silica Gel 3g Sachet', 'Packaging', 'Shenzhen Minghui', 'CN', '381700', 0.03, 1000),
    # Thread
    ('Nylon Bonded Thread T-70', 'Thread', 'American & Efird', 'US', '540249', 6.50, 50),
    ('Polyester Core Thread T-60', 'Thread', 'Coats Group', 'GB', '540710', 5.80, 55),
    # Components
    ('Thermoplastic Stiffener 1.2mm', 'Components', 'Texon International', 'GB', '392190', 3.50, 75),
    ('Heel Counter Moulded', 'Components', 'Texon International', 'GB', '640610', 2.80, 90),
    ('Croslite Pellets Batch', 'Components', 'Crocs Inc (supplied)', 'US', '391400', 8.50, 60),
    # Extra base
    ('Flyknit Yarn 2.0 Red', 'Yarn', 'Toray Industries', 'JP', '540233', 18.80, 55),
    ('Flyknit Yarn 2.0 Blue', 'Yarn', 'Toray Industries', 'JP', '540233', 18.60, 58),
    ('Round Laces 110cm', 'Accessories', 'Zecchetto Accessori', 'IT', '560790', 0.90, 180),
    ('Shoe Box 330x230 White', 'Packaging', 'Karteks Banja Luka', 'BA', '481910', 0.72, 350),
    ('EVA Foam Sheet 6mm', 'Foam', 'Foam Italia', 'IT', '391590', 3.80, 80),
]

# Lead time ranges by country
LEAD_TIMES = {
    'JP': (35, 55), 'TW': (30, 50), 'CN': (30, 45), 'US': (25, 40),
    'IT': (7, 18), 'DE': (7, 15), 'NL': (8, 16), 'GB': (10, 21),
    'BA': (2, 5),
}

# ─── EXPAND TO 500 VARIANTS ──────────────────────────────────────────────────

COLOR_SUFFIXES = [
    'Grey', 'Navy', 'Olive', 'Beige', 'Charcoal', 'Sand', 'Coral', 'Teal',
    'Slate', 'Ivory', 'Moss', 'Plum', 'Rust', 'Cream', 'Sage',
]
VERSION_SUFFIXES = ['v2', 'v3', 'Eco', 'Lite', 'Pro', 'HD', 'Ultra']
SIZE_SUFFIXES = ['S', 'M', 'L', 'XL', 'Wide', 'Narrow']

TARGET_INV = 500


def build_inventory():
    rows = []
    mat_id = 1

    # Add all 30 base materials
    for name, cat, supplier, country, hs, price, cons_rate in BASE_MATERIALS:
        lt_lo, lt_hi = LEAD_TIMES[country]
        lead_time = rng.integers(lt_lo, lt_hi + 1)
        reorder = int(cons_rate * (lead_time / 7) * 1.3)
        stock = int(reorder * rng.uniform(0.40, 2.50))
        last_order = datetime(2026, 2, 28) - timedelta(days=int(rng.integers(1, 60)))

        rows.append({
            'material_id': f'MAT_{mat_id:04d}',
            'material_name': name,
            'category': cat,
            'supplier': supplier,
            'country_origin': country,
            'current_stock': stock,
            'reorder_point': reorder,
            'lead_time_days': int(lead_time),
            'unit_price_eur': round(price * rng.uniform(0.95, 1.05), 2),
            'last_order_date': last_order.strftime('%Y-%m-%d'),
            'consumption_rate_daily': int(cons_rate * rng.uniform(0.85, 1.15)),
            'hs_code': hs,
        })
        mat_id += 1

    # Expand with variants until 500
    while len(rows) < TARGET_INV:
        base = BASE_MATERIALS[rng.integers(0, len(BASE_MATERIALS))]
        name, cat, supplier, country, hs, price, cons_rate = base

        # Pick a variant type
        vtype = rng.integers(0, 3)
        if vtype == 0 and cat in ('Yarn', 'Textile', 'Film', 'Accessories'):
            suffix = rng.choice(COLOR_SUFFIXES)
            var_name = f'{name} {suffix}'
        elif vtype == 1:
            suffix = rng.choice(VERSION_SUFFIXES)
            var_name = f'{name} {suffix}'
        else:
            suffix = rng.choice(SIZE_SUFFIXES)
            var_name = f'{name} {suffix}'

        # Skip exact duplicate names
        if any(r['material_name'] == var_name for r in rows):
            continue

        price_var = price * rng.uniform(0.85, 1.20)
        cons_var = cons_rate * rng.uniform(0.3, 1.2)
        lt_lo, lt_hi = LEAD_TIMES[country]
        lead_time = rng.integers(lt_lo, lt_hi + 1)
        reorder = int(cons_var * (lead_time / 7) * 1.3)
        reorder = max(reorder, 5)
        stock = int(reorder * rng.uniform(0.40, 2.50))
        last_order = datetime(2026, 2, 28) - timedelta(days=int(rng.integers(1, 90)))

        rows.append({
            'material_id': f'MAT_{mat_id:04d}',
            'material_name': var_name,
            'category': cat,
            'supplier': supplier,
            'country_origin': country,
            'current_stock': stock,
            'reorder_point': reorder,
            'lead_time_days': int(lead_time),
            'unit_price_eur': round(price_var, 2),
            'last_order_date': last_order.strftime('%Y-%m-%d'),
            'consumption_rate_daily': max(int(cons_var), 1),
            'hs_code': hs,
        })
        mat_id += 1

    return pd.DataFrame(rows)


print("Generating inventory data...")
inv_df = build_inventory()
inv_df.to_csv('data/supply_chain/inventory.csv', index=False)
print(f"  Saved inventory.csv: {len(inv_df):,} rows")

# ─── DIO 2: purchase_orders.csv (2000 redova) ────────────────────────────────

TARGET_PO = 2000
START_DATE = datetime(2025, 3, 1)
END_DATE = datetime(2026, 2, 28)
DAYS_SPAN = (END_DATE - START_DATE).days

QUALITY_SCORES = [1, 2, 3, 4, 5]
QUALITY_PROBS = [0.02, 0.05, 0.15, 0.45, 0.33]

# Collect all unique suppliers with their materials
supplier_materials = {}
for _, row in inv_df.iterrows():
    sup = row['supplier']
    if sup not in supplier_materials:
        supplier_materials[sup] = []
    supplier_materials[sup].append(row.to_dict())

suppliers = list(supplier_materials.keys())


def generate_purchase_orders():
    rows = []
    po_num = 1

    for _ in range(TARGET_PO):
        # Pick supplier, then pick a material from that supplier
        sup = rng.choice(suppliers)
        mats = supplier_materials[sup]
        mat_row = mats[rng.integers(0, len(mats))]

        order_date = START_DATE + timedelta(days=int(rng.integers(0, DAYS_SPAN)))
        lead_time = mat_row['lead_time_days']
        expected_delivery = order_date + timedelta(days=lead_time)

        # 25% chance of delay (exponential, avg 5 days)
        if rng.random() < 0.25:
            delay = max(1, int(rng.exponential(5)))
        else:
            delay = 0
        actual_delivery = expected_delivery + timedelta(days=delay)

        qty_ordered = int(mat_row['consumption_rate_daily'] * rng.uniform(5, 30))
        qty_ordered = max(qty_ordered, 10)

        # 8% incomplete delivery
        if rng.random() < 0.08:
            qty_received = int(qty_ordered * rng.uniform(0.60, 0.95))
        else:
            qty_received = qty_ordered

        unit_price = mat_row['unit_price_eur'] * rng.uniform(0.97, 1.03)
        total = round(qty_received * unit_price, 2)
        quality_score = int(rng.choice(QUALITY_SCORES, p=QUALITY_PROBS))

        rows.append({
            'po_number': f'PO-{po_num:05d}',
            'date': order_date.strftime('%Y-%m-%d'),
            'supplier': sup,
            'material_id': mat_row['material_id'],
            'qty_ordered': qty_ordered,
            'qty_received': qty_received,
            'unit_price': round(unit_price, 2),
            'total_eur': total,
            'expected_delivery': expected_delivery.strftime('%Y-%m-%d'),
            'actual_delivery': actual_delivery.strftime('%Y-%m-%d'),
            'delay_days': delay,
            'quality_score': quality_score,
        })
        po_num += 1

    return pd.DataFrame(rows)


print("\nGenerating purchase orders...")
po_df = generate_purchase_orders()
po_df = po_df.sort_values('date').reset_index(drop=True)
po_df.to_csv('data/supply_chain/purchase_orders.csv', index=False)
print(f"  Saved purchase_orders.csv: {len(po_df):,} rows")

# ─── SUMMARY ─────────────────────────────────────────────────────────────────

total_value = po_df['total_eur'].sum()
delayed = (po_df['delay_days'] > 0).sum()
incomplete = (po_df['qty_received'] < po_df['qty_ordered']).sum()

print(f"\n{'='*55}")
print(f"SUMMARY")
print(f"{'='*55}")
print(f"Inventory rows:       {len(inv_df):,}")
print(f"Purchase order rows:  {len(po_df):,}")
print(f"Total PO value:       €{total_value:,.2f}")
print(f"Delayed deliveries:   {delayed:,} ({delayed/len(po_df)*100:.1f}%)")
print(f"Incomplete deliveries:{incomplete:,} ({incomplete/len(po_df)*100:.1f}%)")
print(f"\nTop 5 suppliers by PO value:")
top_sup = po_df.groupby('supplier')['total_eur'].sum().sort_values(ascending=False).head(5)
for sup, val in top_sup.items():
    print(f"  {sup:30s} €{val:>12,.2f}")
print(f"\nInventory by category:")
cat_stats = inv_df.groupby('category').agg(
    count=('material_id', 'count'),
    avg_price=('unit_price_eur', 'mean'),
).sort_values('count', ascending=False)
for cat, row in cat_stats.iterrows():
    print(f"  {cat:15s} {int(row['count']):>4} items  avg €{row['avg_price']:.2f}")
