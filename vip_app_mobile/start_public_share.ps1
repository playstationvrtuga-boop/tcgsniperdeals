$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonLog = Join-Path $root "public-share-http.log"
$cloudflaredLog = Join-Path $root "public-share-cloudflared.log"
$pythonErr = Join-Path $root "public-share-http.err.log"
$cloudflaredErr = Join-Path $root "public-share-cloudflared.err.log"
$cloudflared = Join-Path $root "tools\cloudflared.exe"
$python = (Get-Command python).Source
$apk = Join-Path $root "android\app\build\outputs\apk\debug\app-debug.apk"

function Start-DetachedProcess {
  param(
    [string]$FilePath,
    [string]$Arguments,
    [string]$WorkingDirectory,
    [string]$StdOutPath,
    [string]$StdErrPath
  )

  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $FilePath
  $psi.Arguments = $Arguments
  $psi.WorkingDirectory = $WorkingDirectory
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true

  $process = New-Object System.Diagnostics.Process
  $process.StartInfo = $psi

  $outWriter = [System.IO.StreamWriter]::new($StdOutPath, $false)
  $errWriter = [System.IO.StreamWriter]::new($StdErrPath, $false)

  $process.add_OutputDataReceived({
    param($sender, $args)
    if ($null -ne $args.Data) {
      $outWriter.WriteLine($args.Data)
      $outWriter.Flush()
    }
  })
  $process.add_ErrorDataReceived({
    param($sender, $args)
    if ($null -ne $args.Data) {
      $errWriter.WriteLine($args.Data)
      $errWriter.Flush()
    }
  })

  [void]$process.Start()
  $process.BeginOutputReadLine()
  $process.BeginErrorReadLine()
  return [pscustomobject]@{
    Process = $process
    OutWriter = $outWriter
    ErrWriter = $errWriter
  }
}

if (!(Test-Path $apk)) {
  Write-Error "APK not found at $apk"
  exit 1
}

if (!(Test-Path $cloudflared)) {
  Write-Error "cloudflared not found at $cloudflared"
  exit 1
}

if (!(Test-Path $python)) {
  Write-Error "python executable not found"
  exit 1
}

foreach ($log in @($pythonLog, $cloudflaredLog, $pythonErr, $cloudflaredErr)) {
  if (Test-Path $log) { Remove-Item $log -Force }
}

$http = Start-DetachedProcess -FilePath $python -Arguments "-m http.server 8787 --bind 127.0.0.1" -WorkingDirectory $root -StdOutPath $pythonLog -StdErrPath $pythonErr
Start-Sleep -Seconds 2
$tunnel = Start-DetachedProcess -FilePath $cloudflared -Arguments "tunnel --url http://127.0.0.1:8787 --no-autoupdate --protocol http2" -WorkingDirectory $root -StdOutPath $cloudflaredLog -StdErrPath $cloudflaredErr

$url = $null
for ($i = 0; $i -lt 60; $i++) {
  Start-Sleep -Milliseconds 750
  if (Test-Path $cloudflaredLog) {
    $match = Select-String -Path $cloudflaredLog -Pattern "https://[-a-z0-9]+\.trycloudflare\.com" | Select-Object -Last 1
    if ($match) {
      $url = $match.Matches[0].Value
      break
    }
  }
}

Write-Output ("HTTP_PID=" + $http.Process.Id)
Write-Output ("TUNNEL_PID=" + $tunnel.Process.Id)
if ($url) {
  Write-Output ("PUBLIC_URL=" + $url + "/download.html")
} else {
  Write-Output "PUBLIC_URL_NOT_FOUND_YET"
  if (Test-Path $cloudflaredLog) {
    Get-Content $cloudflaredLog -Tail 50
  }
  if (Test-Path $cloudflaredErr) {
    Get-Content $cloudflaredErr -Tail 50
  }
}
