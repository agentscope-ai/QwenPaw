# QwenPaw Desktop Application Guide

> ⚠️ **Beta Version Notice**
>
> The desktop application is currently in Beta testing phase with the following known limitations:
>
> - **Incomplete compatibility testing**: Not fully tested across all system versions and hardware configurations
> - **Potential performance issues**: Startup time, memory usage, and other performance aspects may need further optimization
> - **Features under development**: Some features may be unstable or missing
>
> We welcome your feedback to help improve product quality.

**Download**: [GitHub Releases][releases]

This guide explains how to install and use the QwenPaw Desktop application on Windows and macOS.

[releases]: https://github.com/agentscope-ai/QwenPaw/releases

## Important Notice

**The first launch may take a considerable amount of time (10-60 seconds or more, depending on your system configuration).** The application needs to initialize the Python environment, load dependencies, and start the web service. Please be patient while waiting for the window to appear. Subsequent launches will be faster.

## Table of Contents

- [Windows Guide](#windows-guide)
- [macOS Guide](#macos-guide)
- [Technical Support](#technical-support)

---

## Windows Guide

### System Requirements

- **Operating System**: Windows 10 or later
- **Architecture**: x64 (64-bit)

### Installation Steps

1. **Download the installer**
   Download `QwenPaw-Setup-<version>.exe` from the [Release page][releases]

2. **Run the installer**
   Double-click the `.exe` file and follow the installation wizard
   - Default installation location: `C:\Users\<your-username>\AppData\Local\QwenPaw`
   - Desktop and Start Menu shortcuts will be created after installation

### Launch Options

After installation, you'll see **two launch shortcuts**:

#### **QwenPaw Desktop** (Recommended for daily use)

- **Features**: Silent launch, no terminal window, clean interface
- **Use Case**: Normal usage when you don't need to view technical logs
- **How to Launch**: Double-click the "QwenPaw Desktop" icon on desktop or Start Menu
- **Technical Note**: Uses VBScript launcher, runs Python process in background

#### **QwenPaw Desktop (Debug)** (Debug Mode)

- **Features**: Shows terminal window with real-time logging
- **Use Cases**:
  - Need to view error messages when encountering problems
  - Development and testing
  - Need to provide logs when reporting bugs
- **How to Launch**: Double-click "QwenPaw Desktop (Debug)" icon in Start Menu
- **Log Contents**:
  - Application startup information
  - Python error stack traces
  - API call logs
  - Press Ctrl+C or close the window to stop the application

### Common Issues

**Q: The app window is blank/white screen and cannot display properly?**
A: This is usually because the system is missing or has a damaged **Microsoft WebView2** runtime (a small number of Windows 10 devices don't have it pre-installed, and some devices need a repair/reinstall).
Download and install or repair it from the Microsoft website:
[Microsoft WebView2](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
Restart the application afterwards. If the problem persists, launch "QwenPaw Desktop (Debug)" and inspect the terminal output.

**Q: Application doesn't respond after launch?**
A: Use "QwenPaw Desktop (Debug)" mode to view terminal output for error messages

**Q: How to uninstall?**
A: Go to Windows Settings → Apps → Installed apps → Find "QwenPaw Desktop" → Uninstall

**Q: Is the installer safe?**
A:

- The application is **not Microsoft code-signed** (costs $200-800/year), so Windows Defender SmartScreen will show a warning
- This is normal behavior; click "More info" → "Run anyway" to proceed
- The code is completely open source, and the build process is transparently verifiable on GitHub Actions

---

## macOS Guide

### System Requirements

- **Operating System**: macOS 14 (Sonoma) or later
- **Architecture**:
  - ✅ **Apple Silicon (M1/M2/M3/M4)** - Recommended, supports MLX local model acceleration
  - ⚠️ Intel chips - May work, but cannot use MLX acceleration features

### Installation Steps

1. **Download the archive**
   Download `QwenPaw-<version>-macOS.zip` from the [Release page][releases]

2. **Extract**
   Double-click the `.zip` file to extract and get `QwenPaw.app`

3. **Move to Applications folder (Optional)**
   Drag `QwenPaw.app` to the `/Applications` folder

### First Launch: Bypassing System Security Restrictions

#### Why manual trust is needed?

QwenPaw is **not Apple Developer-signed or notarized**, so macOS Gatekeeper will block it by default.

**Why no signature?**

- 📋 Developer signing requires additional cost and procedures; will be added in future releases

**Current impact:**

- ✅ **No functional impact**: Application runs completely normally
- ⚠️ **First-time manual trust required**: One-time operation, permanently effective
- 🔒 **Security**: Open source code is auditable, transparent build process (CI/CD)

#### How to bypass restrictions?

#### Method 1: Right-click to open (Recommended)

1. **Right-click** (or Control + click) on `QwenPaw.app`
2. Select **"Open"** from the menu
3. In the dialog that appears, click the **"Open"** button again
4. ✅ After this, you can double-click to launch normally without further prompts

#### Method 2: System Settings to bypass blocking

If still blocked:

1. Open **System Settings → Privacy & Security**
2. Scroll down to find a message like:
   _"'QwenPaw' was blocked from use because it cannot verify the developer"_
3. Click the **"Open Anyway"** or **"Allow"** button
4. Enter your administrator password to confirm

#### Method 3: Terminal command to remove quarantine

```bash
# Remove download quarantine attribute
xattr -cr /Applications/QwenPaw.app
```

⚠️ **Warning**: This method completely removes security checks; only use if you fully trust the application source.

### 🔍 Permission Requests

When first launched, macOS may request the following permissions:

- **Desktop file access permission**
  Used to access your files (if using file-related features)
  - Click **"Allow"** for normal use
  - Click **"Don't Allow"** and the app will still run, but some features may be limited

### Launch Options

#### Normal Launch (Double-click)

- Double-click `QwenPaw.app` to launch
- The app runs in the background and opens a browser window
- Logs are written to: `~/.qwenpaw/desktop.log`

#### Terminal Launch (View real-time logs)

If the app crashes or you need to see detailed logs:

```bash
# Navigate to the application directory
cd /Applications  # or wherever your QwenPaw.app is located

# Set environment variables and launch
APP_ENV="$(pwd)/QwenPaw.app/Contents/Resources/env"
PYTHONPATH= PYTHONHOME="$APP_ENV" "$APP_ENV/bin/python" -m qwenpaw desktop
```

**Advantages of terminal launch:**

- ✅ View all log output in real-time
- ✅ See complete Python error stack traces
- ✅ Convenient for debugging and reporting issues
- ✅ Can add `--log-level debug` for more detailed information

**View log file:**

```bash
# View recent startup logs
tail -f ~/.qwenpaw/desktop.log
```

### Common Issues

**Q: Nothing happens after double-clicking?**
A:

1. Check the `~/.qwenpaw/desktop.log` file for errors
2. Use the terminal command above to launch and view real-time output

**Q: Message "Apple cannot verify this application"?**
A: Follow the "Bypassing System Security Restrictions" steps above

**Q: How to uninstall?**
A: Drag `QwenPaw.app` to the Trash, then delete the `~/.qwenpaw` configuration folder

**Q: Can I use it on Intel Mac?**
A: Yes, but you cannot use MLX model acceleration (MLX only supports Apple Silicon)

**Q: Why is the app not signed, and why does the system show a risk warning?**

A:

Currently using:

- ✅ **Open source transparency**: All code and build processes are public on GitHub
- ✅ **CI/CD verifiable**: GitHub Actions automated builds with viewable logs
- ✅ **User auditable**: You can review the code and build locally yourself
- ✅ **One-time trust**: Permanently effective after manual trust

---

## Technical Support

- **GitHub Issues**: [Submit an issue](https://github.com/agentscope-ai/QwenPaw/issues)
- **Packaging documentation**: `scripts/pack/README.md` - Technical details and local build guide
- **Log locations**:
  - Windows: View in Debug mode terminal, or `%USERPROFILE%\.qwenpaw\` directory
  - macOS: `~/.qwenpaw/desktop.log`

---

## Usage Recommendations

### Windows Users

- **Daily use**: Use the normal version (no terminal window)
- **Troubleshooting**: Switch to Debug version to view logs

### macOS Users

- **First install**: Make sure to follow the "Bypassing Security Restrictions" steps
- **Debugging issues**: Use terminal launch method to view real-time logs
- **Permission issues**: Allow file access permission on first launch
