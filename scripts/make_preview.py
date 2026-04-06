#!/usr/bin/env python3
"""
Generate a self-contained HTML preview of an .h5ad file for browser testing.

Usage:
    conda run -n anndata_env python make_preview.py <file.h5ad> [output.html]

Embeds the full summary + all slot previews (X, obsm, layers, etc.)
so every clickable block works in the browser without needing the extension.
"""
import sys
import json
import subprocess
import pathlib


def run_reader(reader, h5ad, *args):
    result = subprocess.run(
        [sys.executable, str(reader), str(h5ad), *args],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return {"error": result.stderr[:300]}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse error: {e}"}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    h5ad_path = pathlib.Path(sys.argv[1]).resolve()
    out_path  = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path('preview.html')

    reader = pathlib.Path(__file__).parent.parent / 'python' / 'reader.py'
    viewer = pathlib.Path(__file__).parent.parent / 'media'  / 'viewer.html'

    print(f'Reading {h5ad_path.name} …')
    data = run_reader(reader, h5ad_path)
    if 'error' in data:
        print('Error:', data['error'])
        sys.exit(1)

    n_obs  = data['shape']['n_obs']
    n_vars = data['shape']['n_vars']
    print(f'  {n_obs:,} cells × {n_vars:,} genes')
    print(f'  X normalization: {data["X_normalization"]["label"]}')

    # Pre-fetch all slot previews
    slots = {}

    print('  Fetching X …')
    slots['X'] = run_reader(reader, h5ad_path, 'X')

    for key in data.get('obsm', {}):
        print(f'  Fetching obsm/{key} …')
        slots[f'obsm/{key}'] = run_reader(reader, h5ad_path, 'obsm', key)

    for key in data.get('varm', {}):
        print(f'  Fetching varm/{key} …')
        slots[f'varm/{key}'] = run_reader(reader, h5ad_path, 'varm', key)

    for key in data.get('obsp', {}):
        print(f'  Fetching obsp/{key} …')
        slots[f'obsp/{key}'] = run_reader(reader, h5ad_path, 'obsp', key)

    for key in data.get('varp', {}):
        print(f'  Fetching varp/{key} …')
        slots[f'varp/{key}'] = run_reader(reader, h5ad_path, 'varp', key)

    for key in data.get('layers', {}):
        print(f'  Fetching layers/{key} …')
        slots[f'layers/{key}'] = run_reader(reader, h5ad_path, 'layers', key)

    for key in data.get('uns_keys', []):
        print(f'  Fetching uns/{key} …')
        slots[f'uns/{key}'] = run_reader(reader, h5ad_path, 'uns', key)

    # Inject into HTML
    html = viewer.read_text()
    html = html.replace('/* __INJECT_DATA__ */',
                        f'window.__injectedData = {json.dumps(data)};')
    html = html.replace('/* __INJECT_SLOTS__ */',
                        f'window.__injectedSlots = {json.dumps(slots)};')

    out_path.write_text(html)
    n_slots = len(slots)
    print(f'\nSaved: {out_path}  ({n_slots} slot(s) pre-fetched)')
    print(f'Open:  file://{out_path.resolve()}')


if __name__ == '__main__':
    main()
