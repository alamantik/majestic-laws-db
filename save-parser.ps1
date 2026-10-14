# Копирует код парсера в X:\majestic-laws-parser и пушит в majestic-laws-parser.
$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$dst = "X:\majestic-laws-parser"

if (-not (Test-Path (Join-Path $dst ".git"))) {
    throw "Нет папки бэкапа: $dst (git worktree parser-export)"
}

$files = @(
    "bot.py",
    "check_codex_gaps.py",
    "diagnose.py",
    "law_extract.py",
    "law_splitter.py",
    "law_validate.py",
    "rules_proto.py",
    "sources.json",
    "requirements.txt",
    "index.html",
    "save-parser.ps1",
    ".env"
)

foreach ($name in $files) {
    $from = Join-Path $src $name
    if (Test-Path $from) {
        Copy-Item $from (Join-Path $dst $name) -Force
    }
}

$authSrc = Join-Path $src "auth"
if (Test-Path $authSrc) {
    New-Item -ItemType Directory -Force -Path (Join-Path $dst "auth") | Out-Null
    Copy-Item (Join-Path $authSrc "*") (Join-Path $dst "auth") -Force
}

$icon = Join-Path $src "icons\icon.ico"
if (Test-Path $icon) {
    New-Item -ItemType Directory -Force -Path (Join-Path $dst "icons") | Out-Null
    Copy-Item $icon (Join-Path $dst "icons\icon.ico") -Force
}

Set-Location $dst
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "Нечего сохранять — парсер не менялся."
    exit 0
}

git commit -m "Update parser"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git push parser HEAD:main
Write-Host "Готово: https://github.com/alamantik/majestic-laws-parser"
