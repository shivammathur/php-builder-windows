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
  [string] $Version = '8.0'
)
if(-not(Test-Path $Path)) {
  New-Item -Type 'directory' $Path
}
$ts = '-nts'
if($ThreadSafe) {
  $ts = ''
}
$branch = 'master'
if($Version -eq '8.0') {
  $branch = 'PHP-8.0'
} elseif($Version -eq '8.1') {
  $branch = 'PHP-8.1'
}
$semver = Invoke-RestMethod https://raw.githubusercontent.com/php/php-src/$branch/main/php_version.h | Where-Object { $_  -match 'PHP_VERSION "(.*)"' } | Foreach-Object {$Matches[1]}
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/shivammathur/php-builder-windows/releases/download/php$Version/php-$semver$ts-Win32-vs16-$Architecture.zip" -OutFile $Path\master.zip
Expand-Archive -Path $Path\master.zip -DestinationPath $Path -Force
Copy-Item $Path\php.ini-production -Destination $Path\php.ini
Move-Item -Path $Path\ext\php_oci8*.dll -Destination $Path\ext\php_oci8.dll -Force
$ts = 'nts'
if($ThreadSafe) {
  $ts = 'ts'
}
"xdebug", "pcov" | ForEach-Object { Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/shivammathur/php-extensions-windows/releases/latest/download/php$Version`_$ts`_$Architecture`_$_.dll" -OutFile $Path"\ext\php`_$_.dll" }
$ini_content = @"
extension_dir=$Path\ext
default_charset=UTF-8
zend_extension=php_opcache.dll
opcache.enable=1
opcache.jit_buffer_size=256M
opcache.jit=1235
"@
Add-Content -Path $Path\php.ini -Value $ini_content
