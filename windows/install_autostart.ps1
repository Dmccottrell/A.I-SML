<#
install_autostart.ps1 - Makes the Emvryx chat app start by itself when you sign in to Windows, restart if it stops, and keeps the PC awake.

Run it ONCE, in PowerShell opened as Administrator (right-click PowerShell, "Run as administrator"):

    cd C:\Users\Darry\Projects\a.i-sml
    powershell -ExecutionPolicy Bypass -File windows\install_autostart.ps1 -Llama "C:\Users\Darry\Downloads\llama-b11192-bin-win-cpu-x64\llama-server.exe"

Add -Python "C:\path\to\python.exe" if the python you normally run the app with is not the first one on the PATH (find it with:  where.exe python  in a normal, non-admin window).
Use the llama-server.exe that has CUDA (GPU) support if you have one, so the 4070 is used. Add -Preload flare-2.5 (a model id from models.json) to load that model at start, so the first message is not slow. Take it off with:  -Remove

What it does:
  1. Writes .emvryx\start_emvryx.cmd: starts app_server.py, writes a log (.emvryx\server.log) and starts it again 15 seconds after it stops.
  2. Registers a Windows scheduled task "Emvryx App": runs that file when you sign in, never times out, and is started again if it fails.
  3. Turns off sleep and hibernate while the PC is plugged in (the screen may still turn off).
  4. Makes the cloudflared tunnel service start automatically and restart itself if it stops. The fixed address (chat.emvryx.app) is the
     tunnel you already made; this does not change it.
It does NOT change your keys, and it does not open anything to the internet by itself.
#>
param(
    [string]$Repo = (Split-Path -Parent $PSScriptRoot),
    [string]$Llama = "",
    [string]$Python = "",
    [int]$Port = 8000,
    [string]$LlamaArgs = "-ngl 99",
    [string]$Preload = "",
    [switch]$Remove
)
$ErrorActionPreference = "Stop"
$TaskName = "Emvryx App"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed the scheduled task. (Sleep settings and the tunnel service were left as they are.)"
    return
}

if (-not (Test-Path (Join-Path $Repo "app_server.py"))) { throw "app_server.py not found in $Repo (use -Repo to say where the project is)." }
$python = if ($Python) { $Python } else { (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $python -or -not (Test-Path $python)) { throw "Python was not found. Use -Python with the full path of the python.exe you normally run the app with." }
& $python -c "import tokenizers, numpy, regex" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Warning "This Python ($python) is missing packages the app needs. Use the python.exe you normally run the app with (-Python), or run: & `"$python`" -m pip install -r requirements.txt" }
$data = Join-Path $Repo ".emvryx"
New-Item -ItemType Directory -Force -Path $data | Out-Null

# 1. the start file
$llamaPart = if ($Llama) { "--llama-bin `"$Llama`" " } else { "" }
if ($Preload) { $llamaPart += "--preload $Preload " }
$cmd = @"
@echo off
rem Written by windows\install_autostart.ps1. Edit the line that starts with python if you change how you run the app.
cd /d "$Repo"
:again
echo %date% %time% starting >> "$data\server.log"
"$python" app_server.py --port $Port $llamaPart--llama-args "$LlamaArgs" >> "$data\server.log" 2>&1
echo %date% %time% stopped, restarting in 15 seconds >> "$data\server.log"
timeout /t 15 /nobreak > nul
goto again
"@
$startFile = Join-Path $data "start_emvryx.cmd"
Set-Content -Path $startFile -Value $cmd -Encoding ASCII
Write-Host "Wrote $startFile"

# 2. the scheduled task (runs as you, when you sign in)
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$startFile`"" -WorkingDirectory $Repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force `
    -Description "Starts the Emvryx chat app when you sign in" | Out-Null
Write-Host "Registered the scheduled task '$TaskName' (starts at sign-in)."

# 3. no sleep while plugged in
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
Write-Host "Sleep and hibernate are off while plugged in."

# 4. the tunnel service
$svc = Get-Service cloudflared -ErrorAction SilentlyContinue
if ($svc) {
    Set-Service cloudflared -StartupType Automatic
    sc.exe failure cloudflared reset= 86400 actions= restart/5000/restart/5000/restart/30000 | Out-Null
    if ($svc.Status -ne "Running") { Start-Service cloudflared }
    Write-Host "The cloudflared service starts automatically and restarts itself if it stops."
} else {
    Write-Warning "The cloudflared service was not found. Set up the named tunnel first (docs/DEPLOY.md, 'A fixed address')."
}

Write-Host ""
Write-Host "Done. Start it now without rebooting:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Check:  curl.exe -s -o NUL -w '%{http_code}' http://127.0.0.1:$Port/   (200 = running)   and the log:  Get-Content .emvryx\server.log -Tail 20"
Write-Host "It starts when you SIGN IN to Windows. After a restart the PC waits at the sign-in screen until you do (see docs/DEPLOY.md for automatic sign-in and its risk)."
