# QwenPaw Desktop Launcher (PowerShell)
# Shows loading window immediately, then starts Python backend
# Once backend is ready, redirects to the actual app

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Configuration
$script:BackendHost = "127.0.0.1"
$script:BackendPort = 0
$script:BackendProcess = $null
$script:MainWindow = $null
$script:LoadingLabel = $null
$script:ProgressBar = $null

# Find a free port
function Find-FreePort {
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = $listener.LocalEndpoint.Port
    $listener.Stop()
    return $port
}

# Check if backend is ready
function Test-BackendReady {
    param([int]$Port)
    
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $result = $client.BeginConnect($script:BackendHost, $Port, $null, $null)
        $success = $result.AsyncWaitHandle.WaitOne(1000)
        
        if ($success) {
            $client.EndConnect($result)
            return $true
        }
        return $false
    } catch {
        return $false
    } finally {
        if ($client) {
            $client.Close()
        }
    }
}

# Create loading window
function New-LoadingWindow {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "QwenPaw Desktop"
    $form.Size = New-Object System.Drawing.Size(600, 400)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.BackColor = [System.Drawing.Color]::White
    $form.TopMost = $false
    
    # Logo/Title
    $titleLabel = New-Object System.Windows.Forms.Label
    $titleLabel.Text = "QwenPaw"
    $titleLabel.Font = New-Object System.Drawing.Font("Segoe UI", 32, [System.Drawing.FontStyle]::Bold)
    $titleLabel.ForeColor = [System.Drawing.Color]::FromArgb(64, 64, 64)
    $titleLabel.Size = New-Object System.Drawing.Size(500, 60)
    $titleLabel.Location = New-Object System.Drawing.Point(50, 80)
    $titleLabel.TextAlign = "MiddleCenter"
    $form.Controls.Add($titleLabel)
    
    # Loading message
    $script:LoadingLabel = New-Object System.Windows.Forms.Label
    $script:LoadingLabel.Text = "正在启动..."
    $script:LoadingLabel.Font = New-Object System.Drawing.Font("Segoe UI", 12)
    $script:LoadingLabel.ForeColor = [System.Drawing.Color]::FromArgb(128, 128, 128)
    $script:LoadingLabel.Size = New-Object System.Drawing.Size(500, 30)
    $script:LoadingLabel.Location = New-Object System.Drawing.Point(50, 180)
    $script:LoadingLabel.TextAlign = "MiddleCenter"
    $form.Controls.Add($script:LoadingLabel)
    
    # Progress bar
    $script:ProgressBar = New-Object System.Windows.Forms.ProgressBar
    $script:ProgressBar.Location = New-Object System.Drawing.Point(100, 230)
    $script:ProgressBar.Size = New-Object System.Drawing.Size(400, 20)
    $script:ProgressBar.Style = "Marquee"
    $script:ProgressBar.MarqueeAnimationSpeed = 30
    $form.Controls.Add($script:ProgressBar)
    
    # Version info
    $versionLabel = New-Object System.Windows.Forms.Label
    $versionLabel.Text = "v1.1.11"
    $versionLabel.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $versionLabel.ForeColor = [System.Drawing.Color]::FromArgb(192, 192, 192)
    $versionLabel.Size = New-Object System.Drawing.Size(500, 20)
    $versionLabel.Location = New-Object System.Drawing.Point(50, 340)
    $versionLabel.TextAlign = "MiddleCenter"
    $form.Controls.Add($versionLabel)
    
    $script:MainWindow = $form
    return $form
}

# Start Python backend
function Start-Backend {
    param([int]$Port, [string]$LogLevel = "info")
    
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $pythonExe = Join-Path $scriptDir "python.exe"
    
    if (-not (Test-Path $pythonExe)) {
        throw "Python executable not found: $pythonExe"
    }
    
    $env:QWENPAW_LOG_LEVEL = $LogLevel
    
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $pythonExe
    $startInfo.Arguments = "-m qwenpaw app --host $script:BackendHost --port $Port --log-level $LogLevel"
    $startInfo.WorkingDirectory = $scriptDir
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    
    $script:BackendProcess = New-Object System.Diagnostics.Process
    $script:BackendProcess.StartInfo = $startInfo
    $script:BackendProcess.Start() | Out-Null
    
    Write-Host "Backend process started (PID: $($script:BackendProcess.Id))"
}

# Wait for backend to be ready
function Wait-BackendReady {
    param([int]$Port, [int]$TimeoutSeconds = 60)
    
    $startTime = Get-Date
    $elapsed = 0
    
    while ($elapsed -lt $TimeoutSeconds) {
        if (Test-BackendReady -Port $Port) {
            return $true
        }
        
        Start-Sleep -Milliseconds 500
        $elapsed = ((Get-Date) - $startTime).TotalSeconds
        
        # Update UI
        if ($script:LoadingLabel) {
            $script:LoadingLabel.Text = "正在启动... ($([math]::Floor($elapsed))s)"
            $script:MainWindow.Refresh()
        }
    }
    
    return $false
}

# Open browser/webview to backend URL
function Open-BackendApp {
    param([int]$Port)
    
    $url = "http://$script:BackendHost`:$Port"
    Write-Host "Opening backend at: $url"
    
    # Try to use pywebview if available, otherwise fall back to browser
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $pythonExe = Join-Path $scriptDir "python.exe"
    
    $webViewScript = @"
import webview
webview.create_window('QwenPaw Desktop', '$url', width=1280, height=800)
webview.start()
"@
    
    $process = Start-Process -FilePath $pythonExe -ArgumentList "-c `"$webViewScript`"" -WorkingDirectory $scriptDir -PassThru
    return $process
}

# Main entry point
function Main {
    try {
        Write-Host "QwenPaw Desktop Launcher starting..."
        
        # Find free port
        $script:BackendPort = Find-FreePort
        Write-Host "Using port: $script:BackendPort"
        
        # Create and show loading window
        $form = New-LoadingWindow
        $form.Show()
        $form.Refresh()
        
        # Start backend
        Write-Host "Starting backend..."
        Start-Backend -Port $script:BackendPort
        
        # Wait for backend
        Write-Host "Waiting for backend to be ready..."
        $ready = Wait-BackendReady -Port $script:BackendPort -TimeoutSeconds 60
        
        if ($ready) {
            Write-Host "Backend is ready!"
            $script:LoadingLabel.Text = "启动完成，正在打开..."
            $form.Refresh()
            
            Start-Sleep -Milliseconds 500
            
            # Close loading window
            $form.Close()
            
            # Open actual app
            $appProcess = Open-BackendApp -Port $script:BackendPort
            
            # Wait for app to close
            if ($appProcess) {
                $appProcess.WaitForExit()
            }
        } else {
            Write-Error "Backend failed to start within timeout"
            $script:LoadingLabel.Text = "启动失败，请重试"
            $script:LoadingLabel.ForeColor = [System.Drawing.Color]::Red
            $form.Refresh()
            Start-Sleep -Seconds 3
            $form.Close()
        }
    } catch {
        Write-Error "Launcher error: $_"
        if ($script:MainWindow) {
            $script:LoadingLabel.Text = "错误: $_"
            $script:LoadingLabel.ForeColor = [System.Drawing.Color]::Red
            $script:MainWindow.Refresh()
            Start-Sleep -Seconds 3
            $script:MainWindow.Close()
        }
    } finally {
        # Cleanup backend process
        if ($script:BackendProcess -and -not $script:BackendProcess.HasExited) {
            Write-Host "Stopping backend process..."
            $script:BackendProcess.Kill()
            $script:BackendProcess.WaitForExit(5000)
        }
    }
}

# Run main
Main
