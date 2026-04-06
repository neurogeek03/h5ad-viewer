# h5ad Viewer — VS Code Extension

## What This Is
A VS Code extension that provides an interactive viewer for `.h5ad` (AnnData) files. It renders a structured panel showing obs, var, obsm, layers, UMAP, and more — without loading the full file into memory.

## Project Structure
```
src/extension.ts       # VS Code extension entry point — registers the custom editor
python/reader.py       # Python backend — reads h5ad, outputs JSON to stdout
media/viewer.html      # Webview frontend — renders the UI using Plotly
scripts/make_preview.py  # Standalone script for generating static previews
```

## How It Works
1. User opens a `.h5ad` file in VS Code
2. Extension spawns `reader.py <filepath>` as a subprocess
3. `reader.py` reads the file with `anndata` (backed mode = no full load) and prints JSON
4. Webview (`viewer.html`) receives JSON via `postMessage` and renders it
5. On user interaction (e.g. clicking a slot), extension calls `reader.py <file> <slot> [key]`

## Development Workflow (Local Machine)
This extension must be tested locally (not on HPC) because VS Code Server does not support `--extensionDevelopmentPath`.

1. Clone the repo locally
2. Open the folder in VS Code desktop
3. Run `npm install` then `npm run compile`
4. Press `F5` (uses `.vscode/launch.json`) to launch Extension Development Host
5. Open any `.h5ad` file — the viewer opens automatically

## Key Files to Edit
- **Add new slots or data fields**: `python/reader.py` — extend `read_h5ad()` or `fetch_slot()`
- **Change UI layout or interactivity**: `media/viewer.html`
- **Change how extension activates or handles messages**: `src/extension.ts`

## Python Requirements
- `anndata`
- `numpy`
- `pandas`

The Python path is resolved in this order:
1. `h5adViewer.pythonPath` VS Code setting
2. Active interpreter from ms-python.python extension
3. Falls back to `python3`

## Packaging (when ready to distribute)
```bash
npx vsce package
code --install-extension h5ad-viewer-0.1.0.vsix
```

## Notes
- The extension reads files in `backed="r"` mode — safe for large files
- UMAP is capped at 50k cells for performance
- Matrix previews cap at 10 rows × 50 columns
- `out/` and `node_modules/` are gitignored — always run `npm run compile` after cloning
