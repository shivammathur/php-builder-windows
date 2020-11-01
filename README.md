# PHP Builder for Windows

<a href="https://github.com/shivammathur/php-builder-windows" title="PHP Builder Windows"><img alt="Build status" src="https://github.com/shivammathur/php-builder-windows/workflows/Build%20PHP/badge.svg"></a>
<a href="https://github.com/shivammathur/php-builder-windows/blob/main/LICENSE" title="license"><img alt="LICENSE" src="https://img.shields.io/badge/license-MIT-428f7e.svg"></a>
<a href="https://github.com/shivammathur/php-builder-windows#Builds" title="builds"><img alt="PHP Versions Supported" src="https://img.shields.io/badge/php-%3E%3D%208.0-8892BF.svg"></a>

> Build PHP nightly for windows.

## Builds

Following configurations are build nightly.

- `nts-x64`, `nts-x64-AVX`, `ts-x64`, `nts-x86`, `ts-x86`.
- `debug-pack`, `devel=pack` for each configuration.
- `test pack` for the version.

### PHP 8.1.0-dev/master
[https://bintray.com/shivammathur/php/master-windows#files](https://bintray.com/shivammathur/php/master-windows#files)

### PHP 8.0.0-dev
[https://bintray.com/shivammathur/php/8.0-windows#files](https://bintray.com/shivammathur/php/8.0-windows#files)

## Install

```ps1
# Configure
$php_dir = 'C:\tools\php' # Set this as per your setup
$arch    = 'x64'          # Set x64 or x86
$ts      = $False         # Set $False for nts or $True for ts
$version = '8.1'          # Set 8.0 or 8.1

# Install
New-Item -Path C:\tools\php -Type Directory -Force
Invoke-WebRequest -UseBasicParsing -Uri https://github.com/shivammathur/php-extensions-windows/releases/latest/download/Get-PhpNightly.ps1 -OutFile $php_dir\Get-PhpNightly.ps1
. $php_dir\Get-PhpNightly.ps1 -Architecture $arch -ThreadSafe $ts -Path $php_dir -Version $version

# Test
. $php_dir\php -v
```

## License

The code in this project is licensed under the [MIT license](http://choosealicense.com/licenses/mit/).
Please see the [license file](LICENSE) for more information. This project has multiple [dependencies](#dependencies "Dependencies for this project"). Their licenses can be found in their respective repositories.

## Dependencies

- [php/web-rmtools](https://github.com/php/web-rmtools)
- [microsoft/php-sdk-binary-tools](https://github.com/microsoft/php-sdk-binary-tools)
- [Oracle instantclient](https://www.oracle.com/downloads/licenses/instant-client-lic.html)
