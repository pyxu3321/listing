<#
.SYNOPSIS
Windows原生OCR后端，输出JSON；由ocr.py隐藏子进程调用，不访问云端OCR。
.PARAMETER ImagePath
待识别本地图片绝对路径；调用方提供缩放派生图，原件不修改。
.PARAMETER Language
期望识别语言，默认en-US；未安装时回退首个可用语言，并在JSON记录回退。
.NOTES
单个WinRT异步操作最多等待15秒；调用方另设25秒进程超时。
没有语言包时输出unavailable；识别文字不是已验证商品事实，confidence为null。
#>
param([Parameter(Mandatory=$true)][string]$ImagePath, [string]$Language = 'en-US')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
$taskAwaitMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
# 功能：将指定WinRT异步操作转Task，限时等待并返回结果；超时抛错。
# 参数：Operation为异步操作，ResultType为预期WinRT结果类型。
function Wait-Operation($Operation, [Type]$ResultType) {
    $taskPending = $taskAwaitMethod.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    if (-not $taskPending.Wait(15000)) { throw 'OCR operation timed out' }
    return $taskPending.Result
}
$taskLanguages = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages)
$taskChosen = $taskLanguages | Where-Object { $_.LanguageTag -eq $Language } | Select-Object -First 1
if (-not $taskChosen) { $taskChosen = $taskLanguages | Select-Object -First 1 }
if (-not $taskChosen) { @{status='unavailable';error='No installed OCR language'} | ConvertTo-Json -Compress; exit 0 }
$taskEngine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($taskChosen)
if (-not $taskEngine) { throw 'OCR engine creation failed' }
$taskFile = Wait-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
$taskStream = Wait-Operation ($taskFile.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$taskBitmap = $null
try {
    $taskDecoder = Wait-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($taskStream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $taskBitmap = Wait-Operation ($taskDecoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8, [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied)) ([Windows.Graphics.Imaging.SoftwareBitmap])
    if ($taskBitmap.PixelWidth -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension -or $taskBitmap.PixelHeight -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension) { throw 'Image exceeds OCR engine dimension limit' }
    $taskResult = Wait-Operation ($taskEngine.RecognizeAsync($taskBitmap)) ([Windows.Media.Ocr.OcrResult])
    $taskLines = @($taskResult.Lines | ForEach-Object {
        @{text=$_.Text; words=@($_.Words | ForEach-Object { @{text=$_.Text; x=$_.BoundingRect.X; y=$_.BoundingRect.Y; width=$_.BoundingRect.Width; height=$_.BoundingRect.Height} })}
    })
    @{status='ready';text=$taskResult.Text;lines=$taskLines;engine='windows.media.ocr';language=$taskChosen.LanguageTag;requested_language=$Language;language_fallback=($taskChosen.LanguageTag -ne $Language);width=$taskBitmap.PixelWidth;height=$taskBitmap.PixelHeight;confidence=$null} | ConvertTo-Json -Depth 8 -Compress
} finally {
    if ($taskBitmap) { $taskBitmap.Dispose() }
    $taskStream.Dispose()
}
