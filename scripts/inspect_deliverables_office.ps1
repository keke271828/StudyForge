param([Parameter(Mandatory=$true)][string]$ReportPath)
$ErrorActionPreference='Stop'
$sfReport=Get-Content -LiteralPath $ReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sfDir=Split-Path $ReportPath -Parent
$sfNative=[ordered]@{word='not_checked';ppt='not_checked'}
# Do not attach to or terminate an Office session the user already has open.
if (Get-Process WINWORD -ErrorAction SilentlyContinue) { $sfNative.word='skipped_existing_session' }
else {
  $sfWord=$null;$sfDocument=$null
  try {
    $sfWord=New-Object -ComObject Word.Application
    $sfWord.Visible=$false;$sfWord.DisplayAlerts=0
    $sfDocument=$sfWord.Documents.Open($sfReport.paths.docx,$false,$true)
    $sfDocument.ExportAsFixedFormat((Join-Path $sfDir 'word-native.pdf'),17)
    $sfNative.word='opened_and_rendered'
  } finally {
    if ($sfDocument) { $sfDocument.Close(0);[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($sfDocument) }
    if ($sfWord) { $sfWord.Quit();[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($sfWord) }
  }
}
if (Get-Process POWERPNT -ErrorAction SilentlyContinue) { $sfNative.ppt='skipped_existing_session' }
else {
  $sfPowerPoint=$null;$sfDeck=$null
  try {
    $sfPowerPoint=New-Object -ComObject PowerPoint.Application
    $sfDeck=$sfPowerPoint.Presentations.Open($sfReport.paths.pptx,-1,0,0)
    $sfSlides=Join-Path $sfDir 'ppt-native'
    $sfDeck.Export($sfSlides,'PNG',1600,900)
    $sfNative.ppt='opened_and_rendered'
  } finally {
    if ($sfDeck) { $sfDeck.Close();[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($sfDeck) }
    if ($sfPowerPoint) { $sfPowerPoint.Quit();[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($sfPowerPoint) }
  }
}
$sfReport.native_office=$sfNative
[System.IO.File]::WriteAllText($ReportPath,($sfReport | ConvertTo-Json -Depth 12),[System.Text.UTF8Encoding]::new($false))
$sfNative | ConvertTo-Json
