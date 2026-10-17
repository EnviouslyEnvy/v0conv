import json
import os
import shutil
import subprocess
import tempfile
import time

CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

LIST_DEVICES_SCRIPT = r'''
param([Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Continue'
$destinations = New-Object System.Collections.Generic.List[object]

try {
    $usbLetters = @{}
    $usbDisks = @(Get-CimInstance Win32_DiskDrive | Where-Object {
        $_.InterfaceType -eq 'USB' -or $_.PNPDeviceID -like 'USB*'
    })
    foreach ($disk in $usbDisks) {
        $partitions = @(Get-CimAssociatedInstance -InputObject $disk -ResultClassName Win32_DiskPartition)
        foreach ($part in $partitions) {
            $logicals = @(Get-CimAssociatedInstance -InputObject $part -ResultClassName Win32_LogicalDisk)
            foreach ($logical in $logicals) {
                $usbLetters[[string]$logical.DeviceID] = [string]$disk.Model
            }
        }
    }
    foreach ($disk in @(Get-CimInstance Win32_LogicalDisk)) {
        $letter = [string]$disk.DeviceID
        $isRemovable = [int]$disk.DriveType -eq 2
        $isUsb = $usbLetters.ContainsKey($letter)
        if (-not $isRemovable -and -not $isUsb) { continue }
        $destinations.Add([pscustomobject]@{
            kind = 'drive'
            id = $letter
            volumeName = [string]$disk.VolumeName
            model = [string]$usbLetters[$letter]
            path = ($letter + '\')
            names = @()
            freeBytes = $disk.FreeSpace
        }) | Out-Null
    }
} catch {
}

try {
    $shell = New-Object -ComObject Shell.Application
    $computer = $shell.NameSpace(17)
    foreach ($item in @($computer.Items())) {
        $type = [string]$item.Type
        if ($type -notmatch 'Mobile Phone|Portable Device|Portable|Tablet|Android|MTP|Digital Camera|Phone') {
            continue
        }
        $folder = $item.GetFolder
        if ($null -eq $folder) { continue }
        $storageFolders = @($folder.Items() | Where-Object { $_.IsFolder })
        if ($storageFolders.Count -eq 0) {
            $destinations.Add([pscustomobject]@{
                kind = 'mtp'
                id = [string]$item.Name
                volumeName = [string]$item.Name
                model = [string]$item.Name
                path = ''
                names = @([string]$item.Name)
                freeBytes = $null
            }) | Out-Null
            continue
        }
        foreach ($child in $storageFolders) {
            $deviceName = [string]$item.Name
            $storageName = [string]$child.Name
            $destinations.Add([pscustomobject]@{
                kind = 'mtp'
                id = ($deviceName + '|' + $storageName)
                volumeName = $storageName
                model = $deviceName
                path = ''
                names = @($deviceName, $storageName)
                freeBytes = $null
            }) | Out-Null
        }
    }
} catch {
}

if ($destinations.Count -eq 0) {
    $json = '[]'
} else {
    $json = ConvertTo-Json -InputObject @($destinations.ToArray()) -Depth 5 -Compress
    if ($destinations.Count -eq 1 -and $json.TrimStart().StartsWith('{')) {
        $json = '[' + $json + ']'
    }
}
[System.IO.File]::WriteAllText($OutputPath, $json, (New-Object System.Text.UTF8Encoding $false))
'''

COPY_MTP_SCRIPT = r'''
param(
    [Parameter(Mandatory=$true)][string]$RequestPath,
    [Parameter(Mandatory=$true)][string]$StatusPath
)
$ErrorActionPreference = 'Stop'

function Write-Status([string]$line) {
    [System.IO.File]::AppendAllText($StatusPath, ($line + [Environment]::NewLine), (New-Object System.Text.UTF8Encoding $false))
}

function Resolve-Chain {
    param($Names)
    $names = @($Names)
    $shell = New-Object -ComObject Shell.Application
    $folder = $shell.NameSpace(17)
    foreach ($name in $names) {
        $item = $null
        foreach ($candidate in @($folder.Items())) {
            if ([string]$candidate.Name -eq [string]$name) {
                $item = $candidate
                break
            }
        }
        if ($null -eq $item) { return $null }
        $next = $item.GetFolder
        if ($null -eq $next) { return $null }
        $folder = $next
    }
    return $folder
}

function Ensure-Chain {
    param($Names, [int]$CreateFromIndex)
    $names = @($Names)
    for ($i = 0; $i -lt $names.Count; $i++) {
        $slice = @($names[0..$i])
        $existing = Resolve-Chain -Names $slice
        if ($null -ne $existing) { continue }
        if ($i -lt $CreateFromIndex) {
            throw "Cannot find '$($names[$i])' on the device. Unlock the phone and set USB to File transfer."
        }
        $parent = Resolve-Chain -Names @($names[0..($i - 1)])
        if ($null -eq $parent) {
            throw "Cannot open '$($names[$i - 1])' on the device."
        }
        $parent.NewFolder([string]$names[$i]) | Out-Null
        $deadline = (Get-Date).AddSeconds(20)
        $created = $null
        do {
            Start-Sleep -Milliseconds 400
            $created = Resolve-Chain -Names $slice
            if ($null -ne $created) { break }
        } while ((Get-Date) -lt $deadline)
        if ($null -eq $created) {
            throw "Could not create folder '$($names[$i])' on the device."
        }
    }
}

function Copy-OneFile {
    param($DestNames, [string]$FilePath)
    $leaf = Split-Path -Leaf $FilePath
    $dest = Resolve-Chain -Names $DestNames
    if ($null -eq $dest) { throw "The phone folder closed before '$leaf' could be copied." }
    $existed = $false
    foreach ($candidate in @($dest.Items())) {
        if ([string]$candidate.Name -eq $leaf) { $existed = $true; break }
    }
    $dest.CopyHere($FilePath, (4 + 16 + 512)) | Out-Null
    if ($existed) {
        $length = (Get-Item -LiteralPath $FilePath).Length
        $seconds = [Math]::Max(1, [Math]::Min(30, [Math]::Ceiling($length / 2MB)))
        Start-Sleep -Seconds $seconds
        return
    }
    $deadline = (Get-Date).AddMinutes(15)
    do {
        Start-Sleep -Milliseconds 400
        $dest = Resolve-Chain -Names $DestNames
        if ($null -eq $dest) { continue }
        foreach ($candidate in @($dest.Items())) {
            if ([string]$candidate.Name -eq $leaf) { return }
        }
    } while ((Get-Date) -lt $deadline)
    throw "Timed out copying '$leaf' to the phone."
}

function Copy-Tree {
    param([string]$SourcePath, $DestNames)
    $DestNames = @($DestNames)
    Ensure-Chain -Names $DestNames -CreateFromIndex 2
    foreach ($entry in @(Get-ChildItem -LiteralPath $SourcePath -Force)) {
        if ($entry.PSIsContainer) {
            $childNames = @($DestNames) + [string]$entry.Name
            Copy-Tree -SourcePath $entry.FullName -DestNames $childNames
        } else {
            Copy-OneFile -DestNames $DestNames -FilePath $entry.FullName
            Write-Status ("FILE " + $entry.Name)
        }
    }
}

$request = Get-Content -LiteralPath $RequestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$baseNames = @($request.names)
$subfolder = @($request.subfolder | Where-Object { $_ })
$jobs = @($request.folders)
$index = 0
foreach ($job in $jobs) {
    $index++
    $relative = @($job.relative | Where-Object { $_ })
    $label = ($relative -join '\')
    Write-Status ("FOLDER {0} {1} {2}" -f $index, $jobs.Count, $label)
    $source = [string]$job.source
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Converted folder was not found: $source"
    }
    $destNames = @($baseNames + $subfolder + $relative)
    Copy-Tree -SourcePath $source -DestNames $destNames
    Write-Status ("DONE " + $label)
}
Write-Status 'COMPLETE'
'''


def format_free_space(num_bytes):
    if num_bytes in (None, ''):
        return ''
    try:
        value = float(num_bytes)
    except (TypeError, ValueError):
        return ''
    gib = value / (1024 ** 3)
    if gib >= 1:
        return f'{gib:.1f} GB free'
    return f'{value / (1024 ** 2):.0f} MB free'


def destination_label(destination):
    if destination.get('custom'):
        return destination.get('path') or destination.get('id') or 'Selected folder'
    if destination.get('kind') == 'drive':
        letter = destination.get('path') or destination.get('id') or ''
        volume = destination.get('volumeName') or destination.get('model') or 'USB drive'
        free = format_free_space(destination.get('freeBytes'))
        label = f'{volume} ({letter.rstrip(chr(92))})'
        if free:
            return f'{label} — {free}'
        return label
    device = destination.get('model') or 'Phone'
    storage = destination.get('volumeName') or ''
    if storage and storage != device:
        return f'{device} — {storage}'
    return device


def _run_powershell(script, arguments, timeout):
    temp_dir = tempfile.mkdtemp(prefix='v0conv-phone-')
    script_path = os.path.join(temp_dir, 'phone.ps1')
    try:
        with open(script_path, 'w', encoding='utf-8-sig') as handle:
            handle.write(script)
        command = [
            'powershell',
            '-NoProfile',
            '-NonInteractive',
            '-ExecutionPolicy', 'Bypass',
            '-File', script_path,
            *arguments,
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or '').strip()
            raise RuntimeError(detail or f'PowerShell exited with code {completed.returncode}')
        return temp_dir
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def list_phone_destinations():
    """Return USB drives and phone storage volumes currently visible to Windows."""
    temp_dir = tempfile.mkdtemp(prefix='v0conv-phone-')
    output_path = os.path.join(temp_dir, 'devices.json')
    try:
        kept_dir = _run_powershell(LIST_DEVICES_SCRIPT, ['-OutputPath', output_path], timeout=90)
        with open(output_path, 'r', encoding='utf-8-sig') as handle:
            payload = handle.read().strip() or '[]'
        shutil.rmtree(kept_dir, ignore_errors=True)
        data = json.loads(payload)
        if isinstance(data, dict):
            data = [data]
        destinations = []
        for item in data:
            names = item.get('names') or []
            if isinstance(names, str):
                names = [names]
            destinations.append({
                'kind': item.get('kind') or 'drive',
                'id': item.get('id') or '',
                'volumeName': item.get('volumeName') or '',
                'model': item.get('model') or '',
                'path': item.get('path') or '',
                'names': [str(name) for name in names if name],
                'freeBytes': item.get('freeBytes'),
                'custom': False,
                'useSubfolder': True,
            })
        return destinations
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def iter_copy_jobs(jobs):
    files = []
    for job in jobs:
        source = job['src']
        relative = job['rel']
        for current_dir, _dirs, filenames in os.walk(source):
            for filename in filenames:
                source_path = os.path.join(current_dir, filename)
                inside = os.path.relpath(source_path, source)
                dest_path = os.path.join(relative, inside)
                files.append((source_path, dest_path, relative))
    return files


def copy_folders_to_drive(jobs, dest_root, on_progress, should_cancel):
    """Copy converted folders onto a normal filesystem path. Returns True if finished."""
    files = iter_copy_jobs(jobs)
    total = len(files)
    if total == 0:
        return True
    for index, (source_path, relative_dest, folder_rel) in enumerate(files, start=1):
        if should_cancel():
            return False
        dest_path = os.path.join(dest_root, relative_dest)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copy2(source_path, dest_path)
        on_progress(index, total, folder_rel, os.path.basename(source_path))
    return True


def _read_new_status(status_path, offset):
    if not os.path.exists(status_path):
        return offset, []
    with open(status_path, 'r', encoding='utf-8-sig', errors='replace') as handle:
        handle.seek(offset)
        chunk = handle.read()
        offset = handle.tell()
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    return offset, lines


def copy_folders_to_mtp(destination_names, subfolder_parts, jobs, on_progress, should_cancel, process_holder):
    """Copy converted folders onto a phone exposed through Windows portable devices."""
    temp_dir = tempfile.mkdtemp(prefix='v0conv-phone-')
    request_path = os.path.join(temp_dir, 'request.json')
    status_path = os.path.join(temp_dir, 'status.txt')
    script_path = os.path.join(temp_dir, 'copy.ps1')
    request = {
        'names': list(destination_names),
        'subfolder': list(subfolder_parts),
        'folders': [
            {
                'source': job['src'],
                'relative': [part for part in job['rel'].replace('/', os.sep).split(os.sep) if part and part != '.'],
            }
            for job in jobs
        ],
    }
    file_total = len(iter_copy_jobs(jobs))
    try:
        with open(request_path, 'w', encoding='utf-8-sig') as handle:
            json.dump(request, handle, ensure_ascii=False)
        with open(script_path, 'w', encoding='utf-8-sig') as handle:
            handle.write(COPY_MTP_SCRIPT)
        with open(status_path, 'w', encoding='utf-8-sig') as handle:
            handle.write('')
        command = [
            'powershell',
            '-NoProfile',
            '-NonInteractive',
            '-ExecutionPolicy', 'Bypass',
            '-File', script_path,
            '-RequestPath', request_path,
            '-StatusPath', status_path,
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            creationflags=CREATE_NO_WINDOW,
        )
        process_holder['process'] = process
        offset = 0
        copied = 0
        while True:
            if should_cancel():
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                return False
            offset, lines = _read_new_status(status_path, offset)
            for line in lines:
                if line.startswith('FILE '):
                    copied += 1
                    on_progress(copied, max(file_total, copied), '', line[5:].strip())
                elif line.startswith('ERROR '):
                    raise RuntimeError(line[6:].strip())
                elif line == 'COMPLETE':
                    pass
            if process.poll() is not None:
                break
            time.sleep(0.3)
        offset, lines = _read_new_status(status_path, offset)
        stdout, stderr = process.communicate()
        for line in lines:
            if line.startswith('ERROR '):
                raise RuntimeError(line[6:].strip())
        if process.returncode != 0:
            detail = (stderr or stdout or '').strip()
            if should_cancel():
                return False
            raise RuntimeError(detail or f'The phone copy stopped (code {process.returncode}).')
        return True
    finally:
        process_holder['process'] = None
        shutil.rmtree(temp_dir, ignore_errors=True)
