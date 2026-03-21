const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');

let mainWindow = null;
let pythonProcess = null;

const PYTHON_PORT = 18765;
const PYTHON_HOST = '127.0.0.1';

// Detect if we're in development mode
const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;

// Workaround for unsigned macOS apps: renderer process gets killed by the
// system due to missing code signature. Use ad-hoc signing (codesign --force
// --deep --sign -) in the build script instead of runtime workarounds.
// If still crashing without signing, uncomment the lines below:
// if (!isDev && process.platform === 'darwin') {
//   app.commandLine.appendSwitch('no-sandbox');
//   app.commandLine.appendSwitch('disable-gpu-sandbox');
// }

// Get Python executable path
function getPythonPath() {
  if (isDev) {
    return 'python';
  }

  const runtimeCandidates = [
    path.join(process.resourcesPath, 'python-runtime'),
    path.join(process.resourcesPath, '..', 'python-runtime'),
    path.join(process.resourcesPath, '..', '..', 'python-runtime'),
  ];

  for (const runtimePath of runtimeCandidates) {
    const executableCandidates = process.platform === 'win32'
      ? [
        path.join(runtimePath, 'python.exe'),
        path.join(runtimePath, 'Scripts', 'python.exe'),
      ]
      : [
        path.join(runtimePath, 'bin', 'python'),
        path.join(runtimePath, 'bin', 'python3'),
        path.join(runtimePath, 'python'),
        path.join(runtimePath, 'python3'),
      ];

    for (const executablePath of executableCandidates) {
      if (fs.existsSync(executablePath)) {
        return executablePath;
      }
    }
  }

  if (process.platform === 'win32') {
    return path.join(process.resourcesPath, 'python-runtime', 'python.exe');
  }
  return path.join(process.resourcesPath, 'python-runtime', 'bin', 'python');
}

function getPythonRuntimePath(pythonPath) {
  const parentDir = path.dirname(pythonPath);
  const parentName = path.basename(parentDir).toLowerCase();
  if (parentName === 'bin' || parentName === 'scripts') {
    return path.dirname(parentDir);
  }
  return parentDir;
}

// conda-unpack is now only run during the build phase (build_electron.sh).
// Running it at app startup causes a chicken-and-egg problem: conda-unpack
// is a Python script that needs working Python paths, but those paths are
// exactly what conda-unpack is supposed to fix.

function resolvePythonLayout(pythonRuntimePath) {
  const normalStdlib = path.join(pythonRuntimePath, 'lib', 'python3.10');
  const normalEncodings = path.join(normalStdlib, 'encodings', '__init__.py');
  if (fs.existsSync(normalEncodings)) {
    return {
      mode: 'normal',
      pythonPath: '',
    };
  }

  const legacyStdlib = path.join(pythonRuntimePath, 'python3.10');
  const legacyEncodings = path.join(legacyStdlib, 'encodings', '__init__.py');
  if (fs.existsSync(legacyEncodings)) {
    const legacyDynload = path.join(pythonRuntimePath, 'lib-dynload');
    const pythonPathParts = [legacyStdlib];
    if (fs.existsSync(legacyDynload)) {
      pythonPathParts.push(legacyDynload);
    }
    return {
      mode: 'legacy-flat',
      pythonPath: pythonPathParts.join(path.delimiter),
    };
  }

  return {
    mode: 'unknown',
    pythonPath: '',
  };
}

// Start Python backend
function startPythonBackend() {
  const pythonPath = getPythonPath();
  const pythonRuntimePath = getPythonRuntimePath(pythonPath);
  const pythonLayout = resolvePythonLayout(pythonRuntimePath);
  // Use 'app' command instead of 'desktop' to get a fixed port
  const moduleArgs = ['-m', 'rypaw', 'app', '--port', PYTHON_PORT.toString()];

  console.log(`[RyPaw] Starting Python backend...`);
  console.log(`[RyPaw] Python path: ${pythonPath}`);
  console.log(`[RyPaw] Target URL: http://${PYTHON_HOST}:${PYTHON_PORT}`);
  console.log(`[RyPaw] Is development: ${isDev}`);
  console.log(`[RyPaw] Working directory: ${isDev ? path.join(__dirname, '..') : process.resourcesPath}`);
  console.log(`[RyPaw] process.resourcesPath: ${process.resourcesPath}`);
  console.log(`[RyPaw] Python runtime path: ${pythonRuntimePath}`);
  console.log(`[RyPaw] Python layout mode: ${pythonLayout.mode}`);

  // Check if Python executable exists in production
  if (!isDev) {
    if (!fs.existsSync(pythonPath)) {
      console.error(`[RyPaw] ERROR: Python executable not found at: ${pythonPath}`);
      const runtimeCandidates = [
        path.join(process.resourcesPath, 'python-runtime'),
        path.join(process.resourcesPath, '..', 'python-runtime'),
        path.join(process.resourcesPath, '..', '..', 'python-runtime'),
      ];
      for (const runtimePath of runtimeCandidates) {
        console.error(`[RyPaw] Checked runtime path: ${runtimePath}`);
        try {
          const files = fs.readdirSync(runtimePath);
          files.forEach(file => console.error(`[RyPaw]   - ${file}`));
        } catch (e) {
          console.error(`[RyPaw] Cannot read directory: ${e.message}`);
        }
      }
      return;
    }
    console.log(`[RyPaw] Python executable exists!`);
  }

  pythonProcess = spawn(pythonPath, moduleArgs, {
    cwd: isDev ? path.join(__dirname, '..') : process.resourcesPath,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      RYPAW_LOG_LEVEL: process.env.RYPAW_LOG_LEVEL || 'info',
      PATH: process.env.PATH,
      // In production, set PYTHONHOME only for normal conda layout (lib/python3.10/encodings exists)
      ...(isDev ? {} : (pythonLayout.mode === 'normal' ? { PYTHONHOME: pythonRuntimePath } : {})),
      ...(!isDev && pythonLayout.pythonPath ? { PYTHONPATH: pythonLayout.pythonPath } : {}),
    }
  });

  // Log for debugging
  console.log(`[RyPaw] Process ID: ${pythonProcess.pid}`);

  // Capture stdout
  pythonProcess.stdout.on('data', (data) => {
    const output = data.toString().trim();
    if (output) {
      console.log(`[Python] ${output}`);
    }
  });

  // Capture stderr
  pythonProcess.stderr.on('data', (data) => {
    const error = data.toString().trim();
    if (error) {
      console.error(`[Python Error] ${error}`);
    }
  });

  // Handle process exit
  pythonProcess.on('close', (code) => {
    console.log(`[RyPaw] Python backend exited with code ${code}`);
    pythonProcess = null;
  });

  // Handle process error
  pythonProcess.on('error', (err) => {
    console.error(`[RyPaw] Failed to start Python backend:`, err);
    console.error(`[RyPaw] Error code: ${err.code}`);
    console.error(`[RyPaw] Error errno: ${err.errno}`);
  });
}

// Stop Python backend
function stopPythonBackend() {
  if (pythonProcess) {
    console.log('[RyPaw] Stopping Python backend...');
    pythonProcess.kill('SIGTERM');
    pythonProcess = null;
  }
}

// Create main window
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    title: 'RyPaw Desktop',
    icon: getIconPath(),
    show: false, // Don't show until ready
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
      webSecurity: false,  // Allow loading from local backend
    }
  });

  // Show window when ready to prevent visual flash
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    // DevTools disabled by default - use Cmd+Option+I (Mac) or Ctrl+Shift+I (Win/Linux) to open
  });

  // Log renderer process errors for debugging and auto-reload on crash
  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    console.error('[RyPaw] Renderer process gone:', JSON.stringify(details));
    // Auto-reload unless the user intentionally killed it
    if (details.reason !== 'clean-exit') {
      console.log('[RyPaw] Attempting to reload...');
      setTimeout(() => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.loadURL(`http://${PYTHON_HOST}:${PYTHON_PORT}`)
            .catch(err => console.error('[RyPaw] Reload failed:', err));
        }
      }, 1000);
    }
  });

  mainWindow.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
    console.error(`[RyPaw] Failed to load: ${validatedURL} - ${errorCode} ${errorDescription}`);
  });

  // Log all console messages from renderer
  mainWindow.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    if (level >= 2) { // 2 = warning, 3 = error
      console.error(`[Renderer] ${message} (${sourceId}:${line})`);
    }
  });

  // Load the app
  mainWindow.loadURL(`http://${PYTHON_HOST}:${PYTHON_PORT}`)
    .catch((err) => {
      console.error('[RyPaw] Failed to load app:', err);
      // Show built-in error page (data URL to avoid file:// restrictions)
      const errorHTML = `
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="UTF-8">
          <style>
            body { font-family: -apple-system, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }
            .error-container { text-align: center; padding: 40px; background: rgba(255,255,255,0.1); border-radius: 20px; backdrop-filter: blur(10px); }
            h1 { font-size: 24px; margin-bottom: 10px; }
            p { font-size: 16px; opacity: 0.9; }
            .info { font-size: 14px; opacity: 0.8; padding: 15px; background: rgba(0,0,0,0.2); border-radius: 10px; margin-top: 20px; }
            code { font-family: monospace; background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 4px; }
          </style>
        </head>
        <body>
          <div class="error-container">
            <h1>⚠️ Connection Failed</h1>
            <p>Could not connect to the RyPaw backend server.</p>
            <div class="info">
              <strong>Target:</strong> <code>http://${PYTHON_HOST}:${PYTHON_PORT}</code><br>
              <strong>Error:</strong> ${err.message}<br><br>
              Please check if the Python backend is running.<br>
              You can also check the Console for more details.
            </div>
          </div>
        </body>
        </html>
      `;
      mainWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(errorHTML));
    });

  // Handle window closed
  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// Get icon path based on platform
function getIconPath() {
  if (process.platform === 'win32') {
    return path.join(__dirname, 'assets', 'icon.ico');
  } else if (process.platform === 'darwin') {
    return path.join(__dirname, 'assets', 'icon.icns');
  } else {
    return path.join(__dirname, 'assets', 'icon.png');
  }
}

// Check if Python backend is ready
async function waitForBackend(timeout = 90000) {
  const startTime = Date.now();
  const url = `http://${PYTHON_HOST}:${PYTHON_PORT}`;

  console.log(`[RyPaw] Waiting for backend at ${url}...`);

  while (Date.now() - startTime < timeout) {
    try {
      const response = await fetch(url, { method: 'HEAD', mode: 'no-cors' });
      // If we get here, the port is open (even if CORS blocks the response)
      console.log(`[RyPaw] Backend is ready!`);
      return true;
    } catch (error) {
      // Backend not ready yet, wait and retry
      await new Promise(resolve => setTimeout(resolve, 500));
    }
  }

  throw new Error(`Backend did not start within ${timeout}ms`);
}

// App lifecycle
app.whenReady().then(async () => {
  // Start Python backend first
  startPythonBackend();

  // Wait for backend to be ready, then create window
  try {
    await waitForBackend();
    createWindow();
  } catch (error) {
    console.error('[RyPaw] Failed to start backend:', error);
    // Show error page
    createWindow();
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    // Stop Python backend when all windows closed
    stopPythonBackend();
    app.quit();
  }
});

app.on('before-quit', () => {
  // Ensure Python backend is stopped
  stopPythonBackend();
});

// IPC handlers
ipcMain.handle('get-app-version', () => {
  return app.getVersion();
});

ipcMain.handle('get-app-path', (event, name) => {
  return app.getPath(name);
});

ipcMain.handle('restart-app', () => {
  app.relaunch();
  app.exit();
});

// Auto-update (optional - requires setup)
if (!isDev) {
  try {
    const { autoUpdater } = require('electron-updater');

    autoUpdater.setFeedURL({
      provider: 'github',
      owner: 'your-org',  // TODO: replace with your real GitHub org/user
      repo: 'rypaw'
    });

    autoUpdater.on('update-available', (info) => {
      console.log('[RyPaw] Update available:', info.version);
    });

    autoUpdater.on('update-downloaded', (info) => {
      console.log('[RyPaw] Update downloaded:', info.version);
    });

    autoUpdater.on('error', (err) => {
      console.error('[RyPaw] Update error:', err);
    });

    autoUpdater.checkForUpdatesAndNotify().catch((err) => {
      console.error('[RyPaw] checkForUpdatesAndNotify failed:', err);
    });
  } catch (err) {
    console.error('[RyPaw] Auto-updater init failed:', err);
  }
}
