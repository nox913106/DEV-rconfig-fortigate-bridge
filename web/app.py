#!/usr/bin/env python3
"""
Fortigate 備份瀏覽器 - Flask 後端
提供 FortigateFirewalls 目錄的瀏覽與下載 API
"""

import os
from datetime import date, datetime
from pathlib import Path
from flask import Flask, jsonify, send_file, render_template, abort

app = Flask(__name__)

FORTIGATE_DIR = Path(
    os.getenv('RCONFIG_DATA_DIR', '/rconfig/storage/app/rconfig/data')
) / 'FortigateFirewalls'

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def _valid_segment(s: str) -> bool:
    """防止 path traversal：不允許 .., /, \\ 等字元"""
    return bool(s) and '..' not in s and '/' not in s and '\\' not in s


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/devices')
def list_devices():
    if not FORTIGATE_DIR.exists():
        return jsonify([])

    devices = []
    for device_dir in sorted(FORTIGATE_DIR.iterdir()):
        if not device_dir.is_dir():
            continue

        latest_date = None
        total_files = 0

        for year_dir in sorted(device_dir.iterdir(), reverse=True):
            if not year_dir.is_dir() or not year_dir.name.isdigit():
                continue
            for mon_dir in sorted(year_dir.iterdir(), reverse=True,
                                   key=lambda d: MONTHS.index(d.name) if d.name in MONTHS else -1):
                if not mon_dir.is_dir() or mon_dir.name not in MONTHS:
                    continue
                for day_dir in sorted(mon_dir.iterdir(), reverse=True):
                    if not day_dir.is_dir():
                        continue
                    files = [f for f in day_dir.iterdir() if f.is_file()]
                    if files:
                        total_files += len(files)
                        if latest_date is None:
                            mon_num = MONTHS.index(mon_dir.name) + 1
                            latest_date = (
                                f"{year_dir.name}-{mon_num:02d}"
                                f"-{day_dir.name.zfill(2)}"
                            )

        days_ago = None
        if latest_date:
            try:
                last_dt = datetime.strptime(latest_date, '%Y-%m-%d').date()
                days_ago = (date.today() - last_dt).days
            except ValueError:
                pass

        devices.append({
            'name': device_dir.name,
            'latest': latest_date,
            'totalFiles': total_files,
            'daysAgo': days_ago,
            'archived': days_ago is None or days_ago > 30,
        })

    return jsonify(devices)


@app.route('/api/devices/<hostname>/calendar/<int:year>/<int:month>')
def get_calendar_days(hostname, year, month):
    if month < 1 or month > 12:
        abort(400)
    if not _valid_segment(hostname):
        abort(400)

    mon_abbr = MONTHS[month - 1]
    month_dir = FORTIGATE_DIR / hostname / str(year) / mon_abbr

    days = []
    if month_dir.exists():
        for day_dir in month_dir.iterdir():
            if not day_dir.is_dir():
                continue
            has_files = any(f.is_file() for f in day_dir.iterdir())
            if has_files:
                try:
                    days.append(int(day_dir.name))
                except ValueError:
                    pass

    return jsonify(sorted(days))


@app.route('/api/devices/<hostname>/files/<int:year>/<mon_abbr>/<int:day>')
def list_files(hostname, year, mon_abbr, day):
    if mon_abbr not in MONTHS:
        abort(400)
    if not _valid_segment(hostname):
        abort(400)

    day_dir = FORTIGATE_DIR / hostname / str(year) / mon_abbr / f"{day:02d}"

    if not day_dir.exists():
        return jsonify([])

    files = []
    for f in sorted(day_dir.iterdir()):
        if not f.is_file():
            continue
        stat = f.stat()
        files.append({
            'name': f.name,
            'size': stat.st_size,
            'mtime': int(stat.st_mtime),
        })

    return jsonify(files)


@app.route('/download/<hostname>/<int:year>/<mon_abbr>/<int:day>/<path:filename>')
def download_file(hostname, year, mon_abbr, day, filename):
    if mon_abbr not in MONTHS:
        abort(400)
    if not _valid_segment(hostname) or not _valid_segment(filename):
        abort(400)

    file_path = (FORTIGATE_DIR / hostname / str(year)
                 / mon_abbr / f"{day:02d}" / filename)

    if not file_path.exists() or not file_path.is_file():
        abort(404)

    return send_file(file_path, as_attachment=True, download_name=file_path.name)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
