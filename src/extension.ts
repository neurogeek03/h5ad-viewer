import * as vscode from 'vscode';
import * as path from 'path';
import * as cp from 'child_process';
import * as fs from 'fs';

export function activate(context: vscode.ExtensionContext) {
  context.subscriptions.push(
    vscode.window.registerCustomEditorProvider(
      'h5adViewer.editor',
      new H5adEditorProvider(context),
      {
        webviewOptions: { retainContextWhenHidden: true },
        supportsMultipleEditorsPerDocument: false,
      }
    )
  );
}

export function deactivate() {}

// ── Custom Editor Provider ──────────────────────────────────────────────────

class H5adEditorProvider implements vscode.CustomReadonlyEditorProvider {
  constructor(private readonly context: vscode.ExtensionContext) {}

  openCustomDocument(
    uri: vscode.Uri,
    _openContext: vscode.CustomDocumentOpenContext,
    _token: vscode.CancellationToken
  ): vscode.CustomDocument {
    return { uri, dispose: () => {} };
  }

  resolveCustomEditor(
    document: vscode.CustomDocument,
    webviewPanel: vscode.WebviewPanel,
    _token: vscode.CancellationToken
  ): void {
    webviewPanel.webview.options = {
      enableScripts: true,
      localResourceRoots: [
        vscode.Uri.joinPath(this.context.extensionUri, 'media'),
      ],
    };

    webviewPanel.webview.html = this.getHtmlContent(webviewPanel.webview);

    // Handle messages from the webview
    webviewPanel.webview.onDidReceiveMessage(
      (msg) => {
        if (msg.type === 'fetch_slot') {
          this.runReaderSlot(
            document.uri.fsPath,
            msg.slot,
            msg.key,
            webviewPanel.webview
          );
        }
      },
      undefined,
      this.context.subscriptions
    );

    // Run the initial full summary
    this.runReaderFull(document.uri.fsPath, webviewPanel.webview);
  }

  // ── Run reader.py for full summary ──────────────────────────────────────

  private runReaderFull(filePath: string, webview: vscode.Webview): void {
    const readerPath = path.join(this.context.extensionUri.fsPath, 'python', 'reader.py');
    const python = this.getPythonPath();

    const proc = cp.spawn(python, [readerPath, filePath]);
    let stdout = '';
    let stderr = '';

    proc.stdout.on('data', (chunk: Buffer) => { stdout += chunk.toString(); });
    proc.stderr.on('data', (chunk: Buffer) => { stderr += chunk.toString(); });

    proc.on('close', (code) => {
      if (code !== 0) {
        webview.postMessage({ type: 'init', error: stderr || `Process exited with code ${code}` });
        return;
      }
      try {
        const data = JSON.parse(stdout);
        if (data.error) {
          webview.postMessage({ type: 'init', error: data.error });
        } else {
          webview.postMessage({ type: 'init', data });
        }
      } catch (e) {
        webview.postMessage({ type: 'init', error: `Failed to parse output: ${stdout.slice(0, 200)}` });
      }
    });

    proc.on('error', (err) => {
      webview.postMessage({
        type: 'init',
        error: `Could not start Python (${python}): ${err.message}. Ensure Python with anndata is available.`,
      });
    });
  }

  // ── Run reader.py for a specific slot ───────────────────────────────────

  private runReaderSlot(
    filePath: string,
    slot: string,
    key: string | undefined,
    webview: vscode.Webview
  ): void {
    const readerPath = path.join(this.context.extensionUri.fsPath, 'python', 'reader.py');
    const python = this.getPythonPath();
    const args = [readerPath, filePath, slot];
    if (key) { args.push(key); }

    const proc = cp.spawn(python, args);
    let stdout = '';
    let stderr = '';

    proc.stdout.on('data', (chunk: Buffer) => { stdout += chunk.toString(); });
    proc.stderr.on('data', (chunk: Buffer) => { stderr += chunk.toString(); });

    proc.on('close', (code) => {
      if (code !== 0) {
        webview.postMessage({ type: 'error', error: stderr || `Process exited with code ${code}` });
        return;
      }
      try {
        const data = JSON.parse(stdout);
        webview.postMessage({ type: 'slot_data', slot, key, data });
      } catch (e) {
        webview.postMessage({ type: 'error', error: `Failed to parse slot output: ${stdout.slice(0, 200)}` });
      }
    });

    proc.on('error', (err) => {
      webview.postMessage({ type: 'error', error: `Could not start Python: ${err.message}` });
    });
  }

  // ── HTML content ────────────────────────────────────────────────────────

  private getHtmlContent(webview: vscode.Webview): string {
    const htmlPath = path.join(this.context.extensionUri.fsPath, 'media', 'viewer.html');
    let html = fs.readFileSync(htmlPath, 'utf8');

    // Apply CSP and nonce
    const nonce = getNonce();
    html = html.replace(
      '</head>',
      `<meta http-equiv="Content-Security-Policy" content="
        default-src 'none';
        script-src 'nonce-${nonce}' https://cdn.plot.ly;
        style-src 'unsafe-inline';
        img-src ${webview.cspSource} data:;
        connect-src 'none';
      "></head>`
    );

    // Add nonce to inline script tag
    html = html.replace('<script>', `<script nonce="${nonce}">`);

    return html;
  }

  // ── Resolve Python path ─────────────────────────────────────────────────

  private getPythonPath(): string {
    const config = vscode.workspace.getConfiguration('h5adViewer');
    const configured = config.get<string>('pythonPath');
    if (configured && configured.trim()) {
      return configured.trim();
    }
    // Fall back to active Python extension interpreter
    const pythonExt = vscode.extensions.getExtension('ms-python.python');
    if (pythonExt) {
      const api = pythonExt.exports;
      if (api?.settings?.getExecutionDetails) {
        const details = api.settings.getExecutionDetails();
        if (details?.execCommand?.[0]) {
          return details.execCommand[0];
        }
      }
    }
    return 'python3';
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function getNonce(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let result = '';
  for (let i = 0; i < 32; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return result;
}
