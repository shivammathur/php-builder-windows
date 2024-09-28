<#
.Synopsis
Installs PHP nightly.
.Description
Download and installs a nightly version of PHP.
.Parameter Architecture
The architecture of the PHP to be installed (x86 for 32-bit, x64 for 64-bit).
.Parameter ThreadSafe
A boolean value to indicate if the Thread-Safe version should be installed or not.
You usually install the ThreadSafe version if you plan to use PHP with Apache, or the NonThreadSafe version if you'll use PHP in CGI mode.
.Parameter Path
The path of the directory where PHP will be installed.
.Parameter Version
The PHP version
 #>
param (
  [Parameter(Mandatory = $true, Position = 1, HelpMessage = 'Architecture of the PHP to be installed (x86 for 32-bit, x64 for 64-bit)')]
  [ValidateSet('x86', 'x64')]
  [string] $Architecture,
  [Parameter(Mandatory = $true, Position = 2, HelpMessage = 'Install a Thread-Safe version?')]
  [bool] $ThreadSafe,
  [Parameter(Mandatory = $true, Position = 3, HelpMessage = 'The path of the directory where PHP will be installed')]
  [ValidateLength(1, [int]::MaxValue)]
  [string] $Path,
  [Parameter(Mandatory = $false, Position = 4, HelpMessage = 'The PHP version')]
  [ValidateLength(1, [int]::MaxValue)]
  [string] $Version = '8.3'
)

Function Get-File {
  param (
    [string]$Url,
    [string]$FallbackUrl,
    [string]$OutFile,
    [int]$Retries = 3,
    [int]$TimeoutSec = 0
  )

  for ($i = 0; $i -lt $Retries; $i++) {
    try {
      if($null -ne $OutFile) {
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -TimeoutSec $TimeoutSec
      } else {
        Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec
      }
      break;
    } catch {
      if ($i -eq ($Retries - 1) -and ($null -ne $FallbackUrl)) {
        try {
          if($null -ne $OutFile) {
            Invoke-WebRequest -Uri $FallbackUrl -OutFile $OutFile -TimeoutSec $TimeoutSec
          } else {
            Invoke-WebRequest -Uri $FallbackUrl -TimeoutSec $TimeoutSec
          }
        } catch {
          throw "Failed to download the build"
        }
      }
    }
  }
}

if(-not(Test-Path $Path)) {
  New-Item -Type 'directory' $Path
}
$ts = '-nts'
if($ThreadSafe) {
  $ts = ''
}
$branch = 'master'
if($Version -match '8.[0-4]') {
  $branch = "PHP-$Version"
}
$vs = 'vs17'
if($Version -match '8.[0-3]') {
  $vs = 'vs16'
}
$semver = Get-File -Url "https://raw.githubusercontent.com/php/php-src/$branch/main/php_version.h" -FallbackUrl "https://cdn.jsdelivr.net/gh/php/php-src@$branch/main/php_version.h" -TimeoutSec 3 | Where-Object { $_  -match 'PHP_VERSION "(.*)"' } | Foreach-Object {$Matches[1]}
$file = "php-$semver$ts-Win32-$vs-$Architecture.zip"
$repo = "shivammathur/php-builder-windows"
Get-File -Url "https://github.com/$repo/releases/download/php$Version/$file" -FallbackUrl "https://dl.cloudsmith.io/public/$repo/raw/files/$file" -OutFile $Path\master.zip -Retries 3
Expand-Archive -Path $Path\master.zip -DestinationPath $Path -Force
Copy-Item $Path\php.ini-production -Destination $Path\php.ini
Move-Item -Path $Path\ext\php_oci8*.dll -Destination $Path\ext\php_oci8.dll -Force
$ts = 'nts'
if($ThreadSafe) {
  $ts = 'ts'
}
"xdebug", "pcov" | ForEach-Object { Get-File -Url "https://github.com/shivammathur/php-extensions-windows/releases/latest/download/php$Version`_$ts`_$Architecture`_$_.dll" -OutFile $Path"\ext\php`_$_.dll" }
$ini_content = @"
extension_dir=$Path\ext
default_charset=UTF-8
zend_extension=php_opcache.dll
opcache.enable=1
opcache.jit_buffer_size=256M
opcache.jit=1235
"@
Add-Content -Path $Path\php.ini -Value $ini_content
