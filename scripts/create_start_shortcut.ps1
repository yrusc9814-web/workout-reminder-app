$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Split-Path -Parent $ScriptDir
$LauncherPath = Join-Path $ScriptDir 'start_workout_app.cmd'
$ShortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) '运动提醒 App.lnk'

if (-not (Test-Path -LiteralPath $LauncherPath)) {
    throw "启动脚本不存在：$LauncherPath"
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $LauncherPath
$Shortcut.WorkingDirectory = $AppDir
$Shortcut.Description = '启动运动提醒 App 后端并打开浏览器'
$Shortcut.Save()

Write-Host "已创建桌面快捷方式：$ShortcutPath"
