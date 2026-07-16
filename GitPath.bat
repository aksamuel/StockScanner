$gitPath = "C:\Program Files\Git\git-cmd"
$currentPath = [Environment]::GetEnvironmentVariable("Path", "Machine")

if ($currentPath -notlike "*$gitPath*") {
    [Environment]::SetEnvironmentVariable(
        "Path",
        "$currentPath;$gitPath",
        "Machine"
    )
}