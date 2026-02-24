import numpy as np
import pandas as pd
from datetime import datetime, timedelta

np.random.seed(42)

# Period: 2025-03-01 to 2026-02-28, no weekends
start = datetime(2025, 3, 1)
end = datetime(2026, 2, 28)
all_days = pd.date_range(start, end, freq='B')  # Business days only

# Seasonality multiplier by month (1=Jan..12=Dec)
# High: Mar-Jun, Sep-Nov; Low: Jul-Aug, Dec-Jan
SEASON = {
    1: 0.75, 2: 0.85, 3: 0.95, 4: 1.05, 5: 1.10, 6: 1.05,
    7: 0.70, 8: 0.72, 9: 1.00, 10: 1.08, 11: 1.05, 12: 0.73,
}

# Line definitions
# line_id: (type, primary_brand, machines, daily_capacity_range)
LINES = {
    'L1': ('3d_knit', 'Nike', ['SHIMA_01', 'SHIMA_02', 'SHIMA_03'], (550, 700)),
    'L2': ('3d_knit', 'Nike', ['SHIMA_04', 'SHIMA_05', 'SHIMA_06'], (520, 680)),
    'L3': ('assembly', 'Nike', ['STITCH_01', 'STITCH_02', 'SOLE_01'], (450, 600)),
    'L4': ('assembly', 'Crocs', ['STITCH_03', 'STITCH_04', 'SOLE_02'], (480, 650)),
    'L5': ('assembly', 'Crocs', ['STITCH_05', 'STITCH_06', 'SOLE_02'], (460, 620)),
    'L6': ('mixed', 'Decathlon', ['SHIMA_07', 'SHIMA_08', 'STITCH_07'], (400, 560)),
    'L7': ('mixed', 'Decathlon', ['SHIMA_09', 'STITCH_08', 'STITCH_07'], (380, 540)),
    'L8': ('finishing', None, ['SOLE_03', 'SOLE_04'], (400, 580)),
}

# Models per brand
NIKE_MODELS = [
    'Air Max Flyknit Upper',
    'Pegasus 3D Knit Collar',
    'Vaporfly Engineered Mesh',
    'ZoomX Carbon Plate Insert',
    'Dunk Low Textile Upper',
]
CROCS_MODELS = [
    'Classic Clog Strap Assembly',
    'LiteRide Insole Unit',
    'Bayaband Slide Upper',
]
DECATHLON_MODELS = [
    'Kalenji Trail Sole Unit',
    'Quechua Hiking Upper',
    'Kiprun Carbon Plate',
]

# Brand distribution for L8 (finishing) and any overflow
BRAND_WEIGHTS = {'Nike': 0.45, 'Crocs': 0.30, 'Decathlon': 0.25}

SHIFTS = [1, 2, 3]


def pick_brand_and_model(line_id, line_info):
    """Pick brand and model based on line assignment."""
    primary = line_info[1]

    if primary == 'Nike':
        # 85% Nike, 10% Crocs, 5% Decathlon
        brand = np.random.choice(['Nike', 'Crocs', 'Decathlon'], p=[0.85, 0.10, 0.05])
    elif primary == 'Crocs':
        brand = np.random.choice(['Nike', 'Crocs', 'Decathlon'], p=[0.10, 0.80, 0.10])
    elif primary == 'Decathlon':
        brand = np.random.choice(['Nike', 'Crocs', 'Decathlon'], p=[0.10, 0.10, 0.80])
    else:  # L8 finishing
        brand = np.random.choice(
            list(BRAND_WEIGHTS.keys()), p=list(BRAND_WEIGHTS.values())
        )

    if brand == 'Nike':
        model = np.random.choice(NIKE_MODELS)
    elif brand == 'Crocs':
        model = np.random.choice(CROCS_MODELS)
    else:
        model = np.random.choice(DECATHLON_MODELS)

    return brand, model


def generate_rows():
    rows = []

    for day in all_days:
        month = day.month
        season_mult = SEASON[month]

        # Shift 3 runs only 60% of days
        shifts_today = [1, 2]
        if np.random.random() < 0.60:
            shifts_today.append(3)

        for line_id, line_info in LINES.items():
            machines = line_info[2]
            cap_lo, cap_hi = line_info[3]

            # Daily capacity adjusted by season
            daily_cap = int(np.random.randint(cap_lo, cap_hi + 1) * season_mult)

            for shift in shifts_today:
                # Shift capacity: shift 1 & 2 get ~35-40% each, shift 3 gets ~25%
                if shift in (1, 2):
                    shift_frac = np.random.uniform(0.34, 0.40)
                else:
                    shift_frac = np.random.uniform(0.20, 0.28)

                planned_qty = max(int(daily_cap * shift_frac), 30)

                brand, model = pick_brand_and_model(line_id, line_info)
                machine_id = np.random.choice(machines)

                # Downtime
                if np.random.random() < 0.15:
                    downtime = int(np.random.uniform(30, 240))
                else:
                    downtime = int(np.random.uniform(0, 30))

                # Changeover
                changeover = 0
                if np.random.random() < 0.30:
                    changeover = int(np.random.uniform(10, 90))

                # Availability (480 min shift = 8h)
                shift_minutes = 480
                available_minutes = max(shift_minutes - downtime - changeover, 60)
                availability = available_minutes / shift_minutes

                # Performance: how much of planned was attempted
                perf_base = np.random.uniform(0.82, 1.02)
                perf_base *= season_mult ** 0.3  # slight seasonal effect
                performance = min(perf_base, 1.0)

                actual_qty = max(int(planned_qty * availability * performance), 1)

                # Defect rate
                base_defect_rate = np.random.uniform(0.02, 0.08)

                # Nike stricter QC -> more detected defects
                if brand == 'Nike':
                    base_defect_rate *= np.random.uniform(1.2, 1.5)

                # Shift 3 -> 30% more defects (fatigue)
                if shift == 3:
                    base_defect_rate *= 1.30

                defect_qty = max(int(actual_qty * base_defect_rate), 0)

                # Quality
                quality = max(1.0 - (defect_qty / max(actual_qty, 1)), 0.70)

                # OEE
                oee = round(availability * performance * quality, 4)

                # Operator count: 4-12 depending on line type
                if line_info[0] == '3d_knit':
                    operators = np.random.randint(4, 8)
                elif line_info[0] == 'assembly':
                    operators = np.random.randint(8, 13)
                elif line_info[0] == 'finishing':
                    operators = np.random.randint(5, 9)
                else:  # mixed
                    operators = np.random.randint(6, 11)

                rows.append({
                    'date': day.strftime('%Y-%m-%d'),
                    'shift': shift,
                    'line_id': line_id,
                    'brand': brand,
                    'model_name': model,
                    'planned_qty': planned_qty,
                    'actual_qty': actual_qty,
                    'defect_qty': defect_qty,
                    'downtime_minutes': downtime,
                    'changeover_minutes': changeover,
                    'operator_count': operators,
                    'machine_id': machine_id,
                    'oee_score': oee,
                })

    return rows


if __name__ == '__main__':
    print("Generating production data for Sportek d.o.o. ...")
    rows = generate_rows()
    df = pd.DataFrame(rows)

    out_path = 'data/production/production_log.csv'
    df.to_csv(out_path, index=False)

    print(f"\nSaved to: {out_path}")
    print(f"Total rows: {len(df):,}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"Average OEE: {df['oee_score'].mean():.4f} ({df['oee_score'].mean()*100:.1f}%)")
    print(f"\nTotal production by brand:")
    brand_stats = df.groupby('brand').agg(
        total_actual=('actual_qty', 'sum'),
        total_planned=('planned_qty', 'sum'),
        avg_oee=('oee_score', 'mean'),
        rows=('brand', 'count'),
    )
    for brand, row in brand_stats.iterrows():
        pct = row['total_actual'] / brand_stats['total_actual'].sum() * 100
        print(f"  {brand:12s}: {int(row['total_actual']):>10,} pairs "
              f"({pct:5.1f}%) | avg OEE {row['avg_oee']*100:.1f}% | {int(row['rows']):,} rows")
