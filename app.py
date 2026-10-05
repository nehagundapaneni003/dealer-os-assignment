
import csv
import sqlite3
import re

def clean_record_ref(ref):
    if not ref or str(ref).strip().lower() in ['none', 'n/a', '']:
        return None
    clean = re.sub(r'[^A-Z0-9]', '', str(ref).upper())
    if clean.isdigit():
        return f"REC-{clean}"
    if clean.startswith("REC"):
        return f"REC-{clean[3:]}"
        return clean
def parse_numeric(val):
    if not val or str(val).strip().lower() in ['none', 'n/a', '']:
        return None
    try:
        clean_str = str(val).replace(',', '').strip()
        return float(clean_str)
    except ValueError:
        return None
from flask import Flask, render_template, request

app = Flask(__name__)

def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS locations (
        location_id TEXT PRIMARY KEY, org_id TEXT, location_name TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS system_a (
        record_id TEXT PRIMARY KEY, location_id TEXT, raw_value TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS system_b (
        id INTEGER PRIMARY KEY AUTOINCREMENT, record_ref TEXT, location_id TEXT, raw_value TEXT)''')
    conn.commit()
    conn.close()

def load_csv_data():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM locations")
    cursor.execute("DELETE FROM system_a")
    cursor.execute("DELETE FROM system_b")

    # Load locations.csv
    try:
        with open('locations.csv', mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                cursor.execute("INSERT OR IGNORE INTO locations VALUES (?, ?, ?)",
                               (row.get('location_id'), row.get('org_id'), row.get('location_name')))
    except Exception as e:
        print(f"Error reading locations.csv: {e}")

    # Load system_a.csv
    try:
        with open('system_a.csv', mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rec_id =clean_record_ref(row.get('record_id'))
                val = row.get('total_value') or row.get('value') or row.get('base_value')
                cursor.execute("INSERT OR IGNORE INTO system_a VALUES (?, ?, ?)",
                               (rec_id, row.get('location_id'), val))
    except Exception as e:
        print(f"Error reading system_a.csv: {e}")

    # Load system_b.csv
    try:
        with open('system_b.csv', mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                ref_id =clean_record_ref(row.get('record_ref') or row.get('record_id'))
                val = row.get('total_value') or row.get('value') or row.get('base_value')
                cursor.execute("INSERT INTO system_b (record_ref, location_id, raw_value) VALUES (?, ?, ?)",
                               (ref_id, row.get('location_id'), val))
    except Exception as e:
        print(f"Error reading system_b.csv: {e}")

    conn.commit()
    conn.close()

def find_discrepancies():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    cursor.execute("SELECT record_id, location_id, raw_value FROM system_a")
    sys_a = {row[0]: {'loc': row[1], 'val': row[2]} for row in cursor.fetchall()}

    cursor.execute("SELECT record_ref, location_id, raw_value FROM system_b")
    sys_b_rows = cursor.fetchall()

    sys_b_map = {}
    for ref, loc, val in sys_b_rows:
        sys_b_map.setdefault(ref, []).append({'loc': loc, 'val': val})

    discrepancies = []

    for rec_id, a_data in sys_a.items():
        b_matches = sys_b_map.get(rec_id, [])

        if not b_matches:
            discrepancies.append({
                'record_id': rec_id,
                'reason': 'MISSING_IN_SYSTEM_B',
                'val_a': a_data['val'],
                'val_b': 'N/A',
                'location_id': a_data['loc']
            })
        elif len(b_matches) > 1:
            discrepancies.append({
                'record_id': rec_id,
                'reason': 'DUPLICATE_IN_SYSTEM_B',
                'val_a': a_data['val'],
                'val_b': ", ".join([str(m['val']) for m in b_matches]),
                'location_id': a_data['loc']
            })
        else:
            b_val = b_matches[0]['val']
            val_a = parse_numeric(a_data['val'])
            val_b = parse_numeric(b_val)

            if val_b is None:
                discrepancies.append({
                    'record_id': rec_id,
                    'reason': 'MISSING_IN_SYSTEM_B',
                    'val_a': a_data['val'],
                    'val_b': 'N/A',
                    'location_id': a_data['loc']
                })
            elif val_a != val_b:
                discrepancies.append({
                    'record_id': rec_id,
                    'reason': 'VALUE_MISMATCH',
                    'val_a': f"{val_a:.2f}" if val_a is not None else a_data['val'],
                    'val_b': f"{val_b:.2f}",
                    'location_id': a_data['loc']
            
                })

    for ref_id, matches in sys_b_map.items():
        if ref_id not in sys_a:
            for m in matches:
                discrepancies.append({
                    'record_id': ref_id,
                    'reason': 'ORPHAN_ENTRY_IN_SYSTEM_B',
                    'val_a': 'N/A',
                    'val_b': m['val'],
                    'location_id': m['loc']
                })

    conn.close()
    return discrepancies

@app.route('/')
def index():
    reason_filter = request.args.get('reason', '')
    all_discrepancies = find_discrepancies()

    if reason_filter:
        filtered = [d for d in all_discrepancies if d['reason'] == reason_filter]
    else:
        filtered = all_discrepancies

    filtered.sort(key=lambda x: str(x['val_a']))

    return render_template('index.html', discrepancies=filtered, selected_reason=reason_filter)

if __name__ == '__main__':
    init_db()
    load_csv_data()
    app.run(debug=True, port=5000)
