#requires -Version 5.1

[CmdletBinding()]
param(
    [Parameter()]
    [string] $Image = (Join-Path (Split-Path -Parent $PSScriptRoot) 'output\images\sdcard.img'),

    [Alias('h')]
    [switch] $Help,

    [Parameter(DontShow)]
    [switch] $NoRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:ImageArgumentProvided = $PSBoundParameters.ContainsKey('Image')

$script:SectorSize = 512L
$script:AlignmentBytes = 1MB
$script:LargeDeviceBytes = 100GB
$script:DataLabel = 'QBTOS_DATA'

function Show-Usage {
    @'
Usage: build-scripts\imager.ps1 [--image PATH]

Interactively select a whole disk, write the qbtOS SD image, and optionally
create an NTFS QBTOS_DATA partition after the OS.

Options:
  --image PATH Raw or Zstandard-compressed qbtOS SD image
               (default: output\images\sdcard.img)
  -Help        Show PowerShell help: Get-Help .\build-scripts\imager.ps1
'@
}

function Format-ByteSize([UInt64] $Bytes) {
    foreach ($unit in @(
        @{ Name = 'TiB'; Size = 1TB },
        @{ Name = 'GiB'; Size = 1GB },
        @{ Name = 'MiB'; Size = 1MB },
        @{ Name = 'KiB'; Size = 1KB }
    )) {
        if ($Bytes -ge $unit.Size) {
            return ('{0:N1} {1}' -f ($Bytes / $unit.Size), $unit.Name)
        }
    }
    return "$Bytes B"
}

function Show-Panel {
    param([string] $Title, [string[]] $Lines, [ConsoleColor] $Color = 'Cyan')
    $width = [Math]::Min(78, [Math]::Max(48, (($Lines + $Title | ForEach-Object Length | Measure-Object -Maximum).Maximum + 4)))
    $rule = [string]::new([char]0x2500, $width - 2)
    Write-Host ("`n{0}{1}{2}" -f [char]0x250c, $rule, [char]0x2510) -ForegroundColor $Color
    Write-Host ("{0} {1,-$($width - 4)} {2}" -f [char]0x2502, $Title, [char]0x2502) -ForegroundColor $Color
    Write-Host ("{0}{1}{2}" -f [char]0x251c, $rule, [char]0x2524) -ForegroundColor $Color
    foreach ($line in $Lines) {
        foreach ($part in ($line -split "`n")) {
            Write-Host ("{0} {1,-$($width - 4)} {2}" -f [char]0x2502, $part, [char]0x2502)
        }
    }
    Write-Host ("{0}{1}{2}" -f [char]0x2514, $rule, [char]0x2518) -ForegroundColor $Color
}

function Read-Menu {
    param([string] $Title, [string] $Prompt, [object[]] $Items, [int] $DefaultIndex = 0)
    if ($Items.Count -eq 0) { throw "No choices are available for $Title." }
    $selected = [Math]::Max(0, [Math]::Min($DefaultIndex, $Items.Count - 1))
    while ($true) {
        Clear-Host
        Show-Panel $Title @($Prompt, '', 'Use Up/Down, Enter to select, or Esc to cancel.')
        for ($index = 0; $index -lt $Items.Count; $index++) {
            $prefix = if ($index -eq $selected) { '  > ' } else { '    ' }
            $color = if ($index -eq $selected) { 'Cyan' } else { 'Gray' }
            Write-Host ($prefix + $Items[$index].Label) -ForegroundColor $color
        }
        $key = [Console]::ReadKey($true).Key
        switch ($key) {
            'UpArrow' { $selected = ($selected - 1 + $Items.Count) % $Items.Count }
            'DownArrow' { $selected = ($selected + 1) % $Items.Count }
            'Enter' { return $Items[$selected] }
            'Escape' { return $null }
        }
    }
}

function Read-DataSize([UInt64] $MaximumGiB) {
    $default = [string]$MaximumGiB
    while ($true) {
        Clear-Host
        Show-Panel 'qbtOS Data Storage' @(
            'How much free space following the OS do you want?',
            '',
            "Enter a whole number in GiB (maximum $MaximumGiB).",
            'This creates an NTFS QBTOS_DATA partition for bootstrap and storage.',
            'Enter 0 to use your own USB or other external data drive.',
            'Press Ctrl+C to cancel.'
        )
        $answer = Read-Host "Size in GiB [$default]"
        if ([string]::IsNullOrWhiteSpace($answer)) { $answer = $default }
        [UInt64] $value = 0
        if ([UInt64]::TryParse($answer, [ref]$value) -and $value -le $MaximumGiB) { return $value }
        Write-Host "Enter a whole number from 0 through $MaximumGiB." -ForegroundColor Yellow
        [void](Read-Host 'Press Enter to try again')
    }
}

function Read-ImagePath {
    $items = @(
        [pscustomobject]@{ Label = "Default: $Image"; Kind = 'Default' },
        [pscustomobject]@{ Label = 'Enter a custom .img or .img.zst path'; Kind = 'Custom' }
    )
    $choice = Read-Menu 'qbtOS Image' 'Choose the qbtOS image to write.' $items
    if (-not $choice) { return $null }
    if ($choice.Kind -eq 'Default') { return $Image }
    while ($true) {
        Clear-Host
        Show-Panel 'Custom qbtOS Image' @(
            'Enter the full path to a qbtOS .img or .img.zst file.',
            'Press Ctrl+C to cancel.'
        )
        $customPath = Read-Host 'Image path'
        if (Test-Path -LiteralPath $customPath -PathType Leaf) { return $customPath }
        Write-Host "The image does not exist: $customPath" -ForegroundColor Yellow
        [void](Read-Host 'Press Enter to try again')
    }
}

function Expand-ZstdImage([string] $SourcePath, [string] $DestinationPath) {
    $zstd = Get-Command zstd.exe, zstd -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $zstd) {
        throw 'A .img.zst image requires zstd.exe on PATH. Install the official Zstandard CLI, then retry.'
    }
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $zstd.Source
    $start.Arguments = "-q -d --stdout -- `"$SourcePath`""
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    $destination = $null
    try {
        if (-not $process.Start()) { throw 'Could not start zstd.exe.' }
        $destination = [IO.File]::Open($DestinationPath, 'CreateNew', 'Write', 'None')
        $process.StandardOutput.BaseStream.CopyTo($destination)
        $destination.Flush()
        $destination.Dispose(); $destination = $null
        $errorText = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw "zstd.exe could not decompress the image: $($errorText.Trim())"
        }
    } finally {
        if ($destination) { $destination.Dispose() }
        $process.Dispose()
    }
}

function Resolve-ImagerImage([string] $RequestedPath) {
    $sourcePath = (Resolve-Path -LiteralPath $RequestedPath -ErrorAction Stop).Path
    $sourceInfo = Get-Item -LiteralPath $sourcePath
    if ($sourceInfo.Length -le 0) { throw "Image is empty: $sourcePath" }
    if ($sourcePath.EndsWith('.zst', [StringComparison]::OrdinalIgnoreCase)) {
        $temporaryPath = Join-Path ([IO.Path]::GetTempPath()) ("qbtos-imager-{0}.img" -f [Guid]::NewGuid().ToString('N'))
        Write-Host "Decompressing $sourcePath..."
        try {
            Expand-ZstdImage $sourcePath $temporaryPath
            if ((Get-Item -LiteralPath $temporaryPath).Length -le 0) { throw 'The decompressed image is empty.' }
            return [pscustomobject]@{ SourcePath = $sourcePath; WorkingPath = $temporaryPath; TemporaryPath = $temporaryPath }
        } catch {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
            throw
        }
    }
    return [pscustomobject]@{ SourcePath = $sourcePath; WorkingPath = $sourcePath; TemporaryPath = $null }
}

function Confirm-DestructiveWrite {
    param([object] $Disk, [string] $ImagePath, [UInt64] $DataGiB, [string[]] $Volumes)
    $dataSummary = if ($DataGiB -eq 0) {
        'No on-device QBTOS_DATA partition will be created.'
    } else {
        "A $DataGiB GiB QBTOS_DATA NTFS partition will be created."
    }
    Clear-Host
    Show-Panel 'DESTROY ALL DATA?' @(
        'The selected disk and every filesystem on it will be overwritten.', '',
        "Disk: PhysicalDrive$($Disk.Number) - $(Format-ByteSize $Disk.Size) - $($Disk.FriendlyName)",
        "Bus: $($Disk.BusType)    Serial: $($Disk.SerialNumber)",
        "Image: $ImagePath", 'Mounted volumes:', ($Volumes -join ', '), '',
        $dataSummary, '', 'Type ERASE exactly to continue.'
    ) 'Red'
    return ((Read-Host 'Confirmation') -ceq 'ERASE')
}

function Get-UInt32LE([byte[]] $Bytes, [int] $Offset) {
    return [BitConverter]::ToUInt32($Bytes, $Offset)
}

function Set-UInt32LE([byte[]] $Bytes, [int] $Offset, [UInt32] $Value) {
    $encoded = [BitConverter]::GetBytes($Value)
    [Array]::Copy($encoded, 0, $Bytes, $Offset, 4)
}

function Get-MbrEntry([byte[]] $Sector, [int] $Number) {
    $offset = 446 + (($Number - 1) * 16)
    [pscustomobject]@{
        Number = $Number
        Type = $Sector[$offset + 4]
        Start = [UInt64](Get-UInt32LE $Sector ($offset + 8))
        Size = [UInt64](Get-UInt32LE $Sector ($offset + 12))
        Offset = $offset
    }
}

function Assert-BootSector([byte[]] $Sector, [string] $Description) {
    if ($Sector.Length -ne 512 -or $Sector[510] -ne 0x55 -or $Sector[511] -ne 0xAA) {
        throw "$Description does not have a valid MBR signature."
    }
}

function Read-Sector([System.IO.Stream] $Stream, [UInt64] $SectorNumber) {
    $buffer = [byte[]]::new(512)
    $Stream.Position = [Int64]($SectorNumber * 512)
    $read = $Stream.Read($buffer, 0, 512)
    if ($read -ne 512) { throw "Could not read sector $SectorNumber." }
    return ,$buffer
}

function Write-Sector([System.IO.Stream] $Stream, [UInt64] $SectorNumber, [byte[]] $Buffer) {
    if ($Buffer.Length -ne 512) { throw 'A sector write must contain exactly 512 bytes.' }
    $Stream.Position = [Int64]($SectorNumber * 512)
    $Stream.Write($Buffer, 0, 512)
}

function Test-QbtOsImageLayout([string] $Path) {
    $stream = [IO.File]::Open($Path, 'Open', 'Read', 'Read')
    try {
        $mbr = Read-Sector $stream 0
        Assert-BootSector $mbr 'Image'
        if ((Get-UInt32LE $mbr 440) -ne 0x5142544f) { throw 'Image does not have the qbtOS MBR signature.' }
        $p2 = Get-MbrEntry $mbr 2
        $p3 = Get-MbrEntry $mbr 3
        $p4 = Get-MbrEntry $mbr 4
        if ($p2.Type -ne 0x83) { throw 'Image has no Linux system slot A in partition 2.' }
        if ($p3.Type -ne 0x83) { throw 'Image has no Linux system slot B in partition 3.' }
        if ($p4.Type -notin @(0x05, 0x0f)) { throw 'Image does not reserve extended partition 4.' }
        $ebr = Read-Sector $stream $p4.Start
        Assert-BootSector $ebr 'State partition EBR'
        $logical = Get-MbrEntry $ebr 1
        if ($logical.Type -ne 0x83) { throw 'Image has no logical QBTOS_STATE partition 5.' }
        if ((Get-MbrEntry $ebr 2).Type -ne 0) { throw 'Image already contains another logical partition.' }
        return [pscustomobject]@{ Mbr = $mbr; ExtendedStart = $p4.Start; StateEbr = $ebr }
    } finally {
        $stream.Dispose()
    }
}

function Add-QbtOsDataPartition {
    param([System.IO.Stream] $Stream, [UInt64] $ImageBytes, [UInt64] $DataBytes)
    if (($ImageBytes % 512) -ne 0 -or ($DataBytes % 512) -ne 0) { throw 'Partition sizes must be sector-aligned.' }
    $imageSectors = [UInt64]($ImageBytes / 512)
    $dataSectors = [UInt64]($DataBytes / 512)
    $dataEbrSector = $imageSectors
    $dataStartSector = $dataEbrSector + 2048
    $mbr = Read-Sector $Stream 0
    Assert-BootSector $mbr 'Flashed disk'
    $extended = Get-MbrEntry $mbr 4
    if ($extended.Type -notin @(0x05, 0x0f)) { throw 'Flashed disk has no expected extended partition.' }
    $extendedSize = $dataStartSector + $dataSectors - $extended.Start
    foreach ($value in @($dataEbrSector, $dataStartSector, $dataSectors, $extendedSize)) {
        if ($value -gt [UInt32]::MaxValue) { throw 'Requested layout exceeds the MBR 2 TiB address limit.' }
    }
    $stateEbr = Read-Sector $Stream $extended.Start
    Assert-BootSector $stateEbr 'State partition EBR'
    if ((Get-MbrEntry $stateEbr 1).Type -ne 0x83 -or (Get-MbrEntry $stateEbr 2).Type -ne 0) {
        throw 'Flashed disk does not contain the expected single QBTOS_STATE logical partition.'
    }

    Set-UInt32LE $mbr ((Get-MbrEntry $mbr 4).Offset + 12) ([UInt32]$extendedSize)
    $chainOffset = (Get-MbrEntry $stateEbr 2).Offset
    $stateEbr[$chainOffset] = 0
    $stateEbr[$chainOffset + 1] = 0xFE; $stateEbr[$chainOffset + 2] = 0xFF; $stateEbr[$chainOffset + 3] = 0xFF
    $stateEbr[$chainOffset + 4] = 0x0F
    $stateEbr[$chainOffset + 5] = 0xFE; $stateEbr[$chainOffset + 6] = 0xFF; $stateEbr[$chainOffset + 7] = 0xFF
    Set-UInt32LE $stateEbr ($chainOffset + 8) ([UInt32]($dataEbrSector - $extended.Start))
    Set-UInt32LE $stateEbr ($chainOffset + 12) ([UInt32](2048 + $dataSectors))

    $dataEbr = [byte[]]::new(512)
    $entryOffset = 446
    $dataEbr[$entryOffset] = 0
    $dataEbr[$entryOffset + 1] = 0xFE; $dataEbr[$entryOffset + 2] = 0xFF; $dataEbr[$entryOffset + 3] = 0xFF
    $dataEbr[$entryOffset + 4] = 0x07
    $dataEbr[$entryOffset + 5] = 0xFE; $dataEbr[$entryOffset + 6] = 0xFF; $dataEbr[$entryOffset + 7] = 0xFF
    Set-UInt32LE $dataEbr ($entryOffset + 8) 2048
    Set-UInt32LE $dataEbr ($entryOffset + 12) ([UInt32]$dataSectors)
    $dataEbr[510] = 0x55; $dataEbr[511] = 0xAA

    Write-Sector $Stream 0 $mbr
    Write-Sector $Stream $extended.Start $stateEbr
    Write-Sector $Stream $dataEbrSector $dataEbr
    $Stream.Flush()
    return $dataStartSector
}

function Get-CandidateDisks {
    $systemDriveLetter = ($env:SystemDrive).TrimEnd(':')
    $systemDisk = (Get-Partition -DriveLetter $systemDriveLetter | Get-Disk).Number
    @(Get-Disk | ForEach-Object {
        $tags = @()
        if ($_.BusType -in @('USB', 'SD', 'MMC', 'IEEE 1394')) { $tags += 'external' }
        if ($_.Size -gt $script:LargeDeviceBytes) { $tags += 'large device' }
        $suffix = if ($tags.Count) { ' (' + ($tags -join ') (') + ')' } else { '' }
        [pscustomobject]@{
            Label = "PhysicalDrive$($_.Number)  $(Format-ByteSize $_.Size)  $($_.FriendlyName)$suffix"
            Disk = $_
            IsSystemDisk = ($_.Number -eq $systemDisk -or $_.IsBoot -or $_.IsSystem)
        }
    } | Where-Object { -not $_.IsSystemDisk })
}

function Get-DiskVolumeDescriptions([UInt32] $DiskNumber) {
    $items = @(Get-Partition -DiskNumber $DiskNumber -ErrorAction SilentlyContinue | ForEach-Object {
        $volume = $_ | Get-Volume -ErrorAction SilentlyContinue
        if ($volume) {
            $mount = if ($volume.DriveLetter) { "$($volume.DriveLetter):" } else { '(no drive letter)' }
            "$mount $($volume.FileSystemLabel) $($volume.FileSystem)"
        }
    })
    if ($items.Count -eq 0) { return @('none') }
    return $items
}

function Dismount-DiskVolumes([UInt32] $DiskNumber) {
    Get-Partition -DiskNumber $DiskNumber -ErrorAction SilentlyContinue | ForEach-Object {
        $volume = $_ | Get-Volume -ErrorAction SilentlyContinue
        if ($volume -and $volume.DriveLetter) {
            & mountvol.exe "$($volume.DriveLetter):\" /p | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Could not dismount volume $($volume.DriveLetter): on disk $DiskNumber." }
        }
    }
}

function Copy-ImageToStream {
    param([string] $ImagePath, [System.IO.Stream] $Destination)
    $source = [IO.File]::Open($ImagePath, 'Open', 'Read', 'Read')
    try {
        $buffer = [byte[]]::new(4MB)
        [Int64] $written = 0
        while (($count = $source.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $Destination.Write($buffer, 0, $count)
            $written += $count
            Write-Progress -Activity 'Writing qbtOS image' -Status "$(Format-ByteSize $written) of $(Format-ByteSize $source.Length)" -PercentComplete (($written * 100.0) / $source.Length)
        }
        $Destination.Flush()
        Write-Progress -Activity 'Writing qbtOS image' -Completed
    } finally { $source.Dispose() }
}

function Get-CurrentCachedHash([string] $ImagePath) {
    $sidecar = "$ImagePath.sha256"
    if (-not (Test-Path -LiteralPath $sidecar -PathType Leaf)) { return $null }
    if ((Get-Item $ImagePath).LastWriteTimeUtc -gt (Get-Item $sidecar).LastWriteTimeUtc) {
        Write-Warning "Ignoring stale checksum cache: $sidecar"
        return $null
    }
    $lines = @(Get-Content -LiteralPath $sidecar)
    if ($lines.Count -ne 1 -or $lines[0] -notmatch '^([0-9a-fA-F]{64})(?:\s|$)') {
        Write-Warning "Ignoring invalid checksum cache: $sidecar"
        return $null
    }
    return $Matches[1].ToLowerInvariant()
}

function Test-WrittenImage {
    param([string] $ImagePath, [System.IO.Stream] $DiskStream)
    $imageLength = (Get-Item -LiteralPath $ImagePath).Length
    $expected = Get-CurrentCachedHash $ImagePath
    $sha = if ($expected) { [Security.Cryptography.SHA256]::Create() } else { $null }
    $source = if ($expected) { $null } else { [IO.File]::Open($ImagePath, 'Open', 'Read', 'Read') }
    try {
        $DiskStream.Position = 0
        $buffer = [byte[]]::new(4MB)
        $compare = [byte[]]::new(4MB)
        [Int64] $checked = 0
        while ($checked -lt $imageLength) {
            $wanted = [Math]::Min($buffer.Length, $imageLength - $checked)
            $count = $DiskStream.Read($buffer, 0, $wanted)
            if ($count -ne $wanted) { throw "Could not read the complete written image at byte $checked." }
            if ($expected) {
                [void]$sha.TransformBlock($buffer, 0, $count, $null, 0)
            } else {
                $sourceCount = $source.Read($compare, 0, $wanted)
                if ($sourceCount -ne $count) { throw 'Image changed while it was being verified.' }
                for ($i = 0; $i -lt $count; $i++) {
                    if ($buffer[$i] -ne $compare[$i]) { throw "Written image differs at byte $($checked + $i)." }
                }
            }
            $checked += $count
            Write-Progress -Activity 'Verifying written OS image' -PercentComplete (($checked * 100.0) / $imageLength)
        }
        if ($expected) {
            [void]$sha.TransformFinalBlock([byte[]]::new(0), 0, 0)
            $actual = ([BitConverter]::ToString($sha.Hash)).Replace('-', '').ToLowerInvariant()
            if ($actual -ne $expected) { throw "Written image checksum mismatch: expected $expected, got $actual." }
        }
        Write-Progress -Activity 'Verifying written OS image' -Completed
    } finally {
        if ($sha) { $sha.Dispose() }
        if ($source) { $source.Dispose() }
    }
}

function Invoke-QbtOsImager {
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'The qbtOS imager must be run from an elevated PowerShell terminal (Run as administrator).'
    }
    $requestedImage = if ($script:ImageArgumentProvided) { $Image } else { Read-ImagePath }
    if (-not $requestedImage) { Write-Host 'Imaging cancelled.'; return }
    $preparedImage = Resolve-ImagerImage $requestedImage
    try {
    $resolvedImage = $preparedImage.WorkingPath
    $imageInfo = Get-Item -LiteralPath $resolvedImage
    if (($imageInfo.Length % 512) -ne 0) { throw 'Image length is not aligned to a 512-byte sector.' }
    [void](Test-QbtOsImageLayout $resolvedImage)

    $choice = Read-Menu 'qbtOS Imager' 'Select the whole disk to overwrite.' (Get-CandidateDisks)
    if (-not $choice) { Write-Host 'Imaging cancelled.'; return }
    $disk = Get-Disk -Number $choice.Disk.Number
    if ($disk.IsBoot -or $disk.IsSystem) { throw 'The running Windows system disk cannot be selected.' }
    if ($disk.LogicalSectorSize -ne 512) { throw "Selected disk uses $($disk.LogicalSectorSize)-byte logical sectors; qbtOS requires 512." }
    if ($disk.Size -lt $imageInfo.Length) { throw 'Selected disk is smaller than the image.' }
    $available = [Int64]$disk.Size - $imageInfo.Length - $script:AlignmentBytes
    $maximumGiB = if ($available -gt 0) { [UInt64][Math]::Floor($available / 1GB) } else { 0 }
    $dataGiB = Read-DataSize $maximumGiB
    $volumes = Get-DiskVolumeDescriptions $disk.Number
    if (-not (Confirm-DestructiveWrite $disk $preparedImage.SourcePath $dataGiB $volumes)) { Write-Host 'Imaging cancelled.'; return }

    $physicalPath = "\\.\PhysicalDrive$($disk.Number)"
    $stream = $null
    try {
        Dismount-DiskVolumes $disk.Number
        Set-Disk -Number $disk.Number -IsOffline $true
        $stream = [IO.File]::Open($physicalPath, 'Open', 'ReadWrite', 'ReadWrite')
        Copy-ImageToStream $resolvedImage $stream
        Test-WrittenImage $resolvedImage $stream
        [UInt64] $dataStartSector = 0
        if ($dataGiB -gt 0) {
            $dataStartSector = Add-QbtOsDataPartition $stream $imageInfo.Length ($dataGiB * 1GB)
        }
        $stream.Dispose(); $stream = $null
        Set-Disk -Number $disk.Number -IsOffline $false
        Update-HostStorageCache
        Start-Sleep -Seconds 2
        if ($dataGiB -gt 0) {
            $expectedOffset = $dataStartSector * 512
            $partition = Get-Partition -DiskNumber $disk.Number | Where-Object Offset -eq $expectedOffset
            if (-not $partition) { throw "Windows did not discover QBTOS_DATA partition 6 at offset $expectedOffset. Reconnect the disk before formatting it manually." }
            $partition | Format-Volume -FileSystem NTFS -NewFileSystemLabel $script:DataLabel -Confirm:$false -Force | Out-Null
        }
        Clear-Host
        $summary = if ($dataGiB -gt 0) { "$dataGiB GiB of on-device QBTOS_DATA storage (NTFS) was created." } else { 'No on-device QBTOS_DATA storage was created.' }
        Show-Panel 'qbtOS Imager' @("qbtOS was written successfully to PhysicalDrive$($disk.Number).", '', $summary, 'Use Safely Remove Hardware before removing the device.') 'Green'
    } finally {
        if ($stream) { $stream.Dispose() }
        $current = Get-Disk -Number $disk.Number -ErrorAction SilentlyContinue
        if ($current -and $current.IsOffline) {
            try { Set-Disk -Number $disk.Number -IsOffline $false -ErrorAction Stop } catch { Write-Warning "Could not return PhysicalDrive$($disk.Number) online: $($_.Exception.Message)" }
        }
    }
    } finally {
        if ($preparedImage.TemporaryPath) {
            Remove-Item -LiteralPath $preparedImage.TemporaryPath -Force -ErrorAction SilentlyContinue
        }
    }
}

if ($Help -and $MyInvocation.InvocationName -ne '.') {
    Show-Usage
    exit 0
}

if (-not $NoRun -and $MyInvocation.InvocationName -ne '.') {
    try { Invoke-QbtOsImager } catch {
        Write-Error "qbtOS Imager failed: $($_.Exception.Message)"
        exit 1
    }
}
