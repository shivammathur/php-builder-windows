version=$1
directory=$2
(
    cd "$directory" || exit 1
    trunk=https://windows.php.net/downloads/releases
    semver=$(curl -sL "$trunk"/releases.json | jq -r ".[\"$version\"].version")
    if [ "$version" != "${semver%.*}" ]; then
        semver=$(curl -sL "$trunk"/archives/ | grep -Po '(?<=HREF=")[^"]*' | grep -Po "$version.[0-9]+" | sort -V | tail -1)
        trunk="$trunk"/archives
    fi
    curl -sL "$trunk" | grep -Po '(?<=HREF=")[^"]*' | grep -E "$semver" | xargs -n 1 -I{} curl -sLO https://windows.php.net/{}
)
