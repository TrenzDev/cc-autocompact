<#
.SYNOPSIS
  Installs cc-autocompact from this folder into your Claude Code folder (~/.claude). Windows.

.DESCRIPTION
  The one-line install is the plugin marketplace (see the README). This script is the other way:
  from a clone, without a marketplace. It copies the plugin to ~/.claude/mods/cc-autocompact and
  PRINTS the one line you need in ~/.claude/settings.json. It does not touch settings.json unless you
  ask for it with -ApplySettings, and then it saves a backup first.

  It never deletes anything: a previous copy of the plugin is moved to
  ~/.claude/backups/cc-autocompact-<date>/ first. It writes no config.json: the plugin runs on its
  defaults, and your own config.json (in ~/.claude/cc-autocompact/) is never touched.

.PARAMETER ApplySettings
  Also adds the plugin folder to CLAUDE_CODE_PLUGIN_DIRS in settings.json (keeping any folders
  already there), after saving settings.json.bak-<date>. Running it twice adds nothing.

.PARAMETER ClaudeDir
  Claude Code's configuration folder. Defaults to CLAUDE_CONFIG_DIR, or ~/.claude.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1 -ApplySettings
#>
[CmdletBinding()]
param(
  [switch]$ApplySettings,
  [string]$ClaudeDir = $(if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME '.claude' })
)

$ErrorActionPreference = 'Stop'
$Repo = $PSScriptRoot
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false
$Source = Join-Path $Repo 'plugin'
$Dest = Join-Path $ClaudeDir 'mods\cc-autocompact'
$Settings = Join-Path $ClaudeDir 'settings.json'

function Write-Step([string]$text) { Write-Host "`n> $text" -ForegroundColor Cyan }

foreach ($p in @('.claude-plugin\plugin.json', 'hooks\hooks.json', 'hooks\register.ts', 'skills\wrap-up\SKILL.md')) {
  if (-not (Test-Path (Join-Path $Source $p))) { throw "Missing plugin\${p}: run install.ps1 from the repository folder." }
}
New-Item -ItemType Directory -Force -Path $ClaudeDir | Out-Null

# 1. The plugin: the mod, the wrap-up skill and its types
Write-Step 'Plugin cc-autocompact'
if (Test-Path $Dest) {
  $backup = Join-Path $ClaudeDir "backups\cc-autocompact-$Stamp"
  New-Item -ItemType Directory -Force -Path (Split-Path $backup -Parent) | Out-Null
  Move-Item -Path $Dest -Destination $backup
  Write-Host "  Previous copy moved to $backup"
}
$root = (Resolve-Path $Source).Path.TrimEnd('\')
Get-ChildItem -Path $root -Recurse -File -Force |
  Where-Object { $_.FullName -notmatch '\\\.claude-plugin\\types\\' -and $_.Name -notlike '*.test.ts' } |
  ForEach-Object {
    $target = Join-Path $Dest $_.FullName.Substring($root.Length + 1)
    New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
    Copy-Item -Path $_.FullName -Destination $target -Force
  }
Write-Host "  Copied to $Dest"
Write-Host '  No config.json needed: it runs on its defaults. To change one, see config.example.json and the README.'

# 2. settings.json: one variable
$Block = @{ env = @{ CLAUDE_CODE_PLUGIN_DIRS = $Dest } } | ConvertTo-Json -Depth 4

if (-not $ApplySettings) {
  Write-Step "Add this to $Settings"
  Write-Host 'Merge it with what you have. If CLAUDE_CODE_PLUGIN_DIRS already exists, add this folder at the end, after a ";".'
  Write-Host ''
  Write-Host $Block -ForegroundColor Yellow
  Write-Host ''
  Write-Host 'Or run this script again with -ApplySettings and it will add it for you (after a backup).'
} else {
  Write-Step "Updating $Settings"
  $s = $null
  if (Test-Path $Settings) {
    Copy-Item $Settings "$Settings.bak-$Stamp"
    Write-Host "  Backup: $Settings.bak-$Stamp"
    $raw = [System.IO.File]::ReadAllText($Settings, [System.Text.Encoding]::UTF8)
    if (-not [string]::IsNullOrWhiteSpace($raw)) { $s = $raw | ConvertFrom-Json }
  }
  if ($null -eq $s) { $s = New-Object PSObject }
  if (-not ($s.PSObject.Properties.Name -contains 'env')) { $s | Add-Member -NotePropertyName env -NotePropertyValue (New-Object PSObject) }
  $current = $s.env.CLAUDE_CODE_PLUGIN_DIRS
  if ([string]::IsNullOrWhiteSpace($current)) {
    $s.env | Add-Member -NotePropertyName CLAUDE_CODE_PLUGIN_DIRS -NotePropertyValue $Dest -Force
    Write-Host '  Added CLAUDE_CODE_PLUGIN_DIRS'
  } elseif (($current -split ';' | ForEach-Object { $_.Trim().TrimEnd('\', '/') }) -contains $Dest.TrimEnd('\', '/')) {
    Write-Host '  CLAUDE_CODE_PLUGIN_DIRS already has the plugin: nothing to add'
  } else {
    $s.env.CLAUDE_CODE_PLUGIN_DIRS = "$current;$Dest"
    Write-Host '  Added the plugin folder to CLAUDE_CODE_PLUGIN_DIRS (the folders already there stay)'
  }
  # Windows PowerShell 5.1 serializes some arrays badly unless this extended type data is removed
  Remove-TypeData System.Array -ErrorAction SilentlyContinue
  [System.IO.File]::WriteAllText($Settings, ($s | ConvertTo-Json -Depth 64), $Utf8NoBom)
  Write-Host '  settings.json updated.'
}

Write-Step 'Next steps'
Write-Host '  1. Add the "Closing tasks" rule to your CLAUDE.md (README, step 2).'
Write-Host '  2. Restart the Claude Code desktop app, or start a new session in the terminal.'
Write-Host '  3. Type "/" and check that /compact-now is there.'
