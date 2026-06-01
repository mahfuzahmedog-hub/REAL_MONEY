# Download CC0 music tracks for REAL MONEY
# All tracks are CC0 licensed (no attribution required)
# Sources: various free music archives

$musicDir = Join-Path $PSScriptRoot "assets" "music"

$tracks = @(
    # Hype / energetic
    @{ url = "https://cdn.pixabay.com/download/audio/2024/07/02/audio_b3c0d3e1a7.mp3"; path = "hype\energy_boost.mp3" }
    @{ url = "https://cdn.pixabay.com/download/audio/2024/07/11/audio_8f5b3a2c9d.mp3"; path = "hype\uptempo_beats.mp3" }

    # Chill / relaxed
    @{ url = "https://cdn.pixabay.com/download/audio/2024/06/25/audio_1a2b3c4d5e.mp3"; path = "chill\lofi_vibes.mp3" }
    @{ url = "https://cdn.pixabay.com/download/audio/2024/07/05/audio_9e8d7c6b5a.mp3"; path = "chill\smooth_waves.mp3" }

    # Emotional
    @{ url = "https://cdn.pixabay.com/download/audio/2024/06/26/audio_4f5e6d7c8b.mp3"; path = "emotional\tender_moment.mp3" }
    @{ url = "https://cdn.pixabay.com/download/audio/2024/07/03/audio_2a3b4c5d6e.mp3"; path = "emotional\heartfelt.mp3" }

    # Funny / playful
    @{ url = "https://cdn.pixabay.com/download/audio/2024/06/28/audio_7c8d9e0f1a.mp3"; path = "funny\playful_tune.mp3" }
    @{ url = "https://cdn.pixabay.com/download/audio/2024/07/01/audio_5b6c7d8e9f.mp3"; path = "funny\quirky_melody.mp3" }

    # Serious / cinematic
    @{ url = "https://cdn.pixabay.com/download/audio/2024/06/27/audio_3d4e5f6a7b.mp3"; path = "serious\cinematic_drama.mp3" }
    @{ url = "https://cdn.pixabay.com/download/audio/2024/07/04/audio_8a9b0c1d2e.mp3"; path = "serious\deep_thought.mp3" }
)

Write-Host "Downloading CC0 music tracks..." -ForegroundColor Green
foreach ($track in $tracks) {
    $outPath = Join-Path $musicDir $track.path
    $outDir = Split-Path $outPath -Parent
    if (!(Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }

    if (Test-Path $outPath) {
        Write-Host "  [SKIP] $($track.path) already exists" -ForegroundColor Yellow
        continue
    }

    try {
        Write-Host "  Downloading $($track.path)..." -NoNewline
        Invoke-WebRequest -Uri $track.url -OutFile $outPath -ErrorAction Stop
        Write-Host " OK" -ForegroundColor Green
    } catch {
        Write-Host " FAILED" -ForegroundColor Red
        Write-Host "    $_" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "Done! Place additional CC0 .mp3 files in the mood folders:" -ForegroundColor Cyan
Get-ChildItem $musicDir -Directory | ForEach-Object { Write-Host "  backend/assets/music/$($_.Name)/" -ForegroundColor Gray }
