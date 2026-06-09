$ErrorActionPreference = 'Stop'

$url = 'http://127.0.0.1:3000'
$shortcutName = 'Workout Reminder App.url'
$desktopPath = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopPath $shortcutName

function Get-InternetShortcutUrl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $content = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop
    $match = [regex]::Match($content, '(?im)^\s*URL\s*=\s*(.+?)\s*$')
    if (-not $match.Success) {
        return $null
    }

    return $match.Groups[1].Value
}

if (Test-Path -LiteralPath $shortcutPath) {
    $existingUrl = Get-InternetShortcutUrl -Path $shortcutPath
    if ($existingUrl -ne $url) {
        throw "Refusing to overwrite existing unrelated shortcut: $shortcutPath"
    }

    Write-Host "Desktop shortcut already exists: $shortcutPath"
    Write-Host "Target URL: $url"
    return
}

$shortcutContent = @"
[InternetShortcut]
URL=$url
"@

Set-Content -LiteralPath $shortcutPath -Value $shortcutContent -Encoding ASCII -NoNewline

Write-Host "Created desktop shortcut: $shortcutPath"
Write-Host "Target URL: $url"
Write-Host 'If the page does not open, start the backend service first:'
Write-Host 'cd D:/workout-reminder-app-github/workout-app && python -m uvicorn main:app --host 127.0.0.1 --port 3000'
