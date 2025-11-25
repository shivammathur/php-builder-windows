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
  [string] $Version = '8.5'
)

Function Get-File {
  param (
    [string]$Url,
    [string]$FallbackUrl,
    [string]$OutFile = '',
    [int]$Retries = 3,
    [int]$TimeoutSec = 0
  )

  for ($i = 0; $i -lt $Retries; $i++) {
    try {
      if($OutFile -ne '') {
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -TimeoutSec $TimeoutSec
      } else {
        Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec
      }
      break;
    } catch {
      if ($i -eq ($Retries - 1)) {
        if($FallbackUrl) {
          try {
            if($OutFile -ne '') {
              Invoke-WebRequest -Uri $FallbackUrl -OutFile $OutFile -TimeoutSec $TimeoutSec
            } else {
              Invoke-WebRequest -Uri $FallbackUrl -TimeoutSec $TimeoutSec
            }
          } catch {
            throw "Failed to download the assets from $Url and $FallbackUrl"
          }
        } else {
          throw "Failed to download the assets from $Url"
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
if($Version -match '8.[0-5]') {
  Install-Php -Version $Version -Architecture $Architecture -ThreadSafe $ThreadSafe -InstallVC -Path $Path -TimeZone UTC -InitialPhpIni Production -Force
} else {
  $file = "php-$Version.0-dev$ts-Win32-vs17-$Architecture.zip"
  $repo = "shivammathur/php-builder-windows"
  Get-File -Url "https://github.com/$repo/releases/download/php$Version/$file" -FallbackUrl "https://dl.cloudsmith.io/public/$repo/raw/files/$file" -OutFile $Path\master.zip -Retries 3
  Expand-Archive -Path $Path\master.zip -DestinationPath $Path -Force
  Remove-Item -Path $Path\master.zip
  Copy-Item $Path\php.ini-production -Destination $Path\php.ini
}
Move-Item -Path $Path\ext\php_oci8*.dll -Destination $Path\ext\php_oci8.dll -Force
$ts = 'nts'
if($ThreadSafe) {
  $ts = 'ts'
}
"xdebug", "pcov" | ForEach-Object { Get-File -Url "https://github.com/shivammathur/php-extensions-windows/releases/latest/download/php$Version`_$ts`_$Architecture`_$_.dll" -OutFile $Path"\ext\php`_$_.dll" }
$ini_content = @(
  "extension_dir=$Path\ext"
  "default_charset=UTF-8"
  "opcache.enable=1"
  "opcache.jit_buffer_size=256M"
  "opcache.jit=1235"
)
if ($Version -lt [version]'8.5') {
  $ini_content += "zend_extension=php_opcache.dll"
} elseif (Test-Path $Path\ext\php_opcache.dll) {
  Remove-Item $Path\ext\php_opcache.dll -Force
}
Add-Content -Path $Path\php.ini -Value ($ini_content -join [Environment]::NewLine)
