version=$1
directory=$2
(
    cd "$directory" || exit 1
    trunk=https://downloads.php.net/~windows/releases
    semver=$(curl -sL "$trunk"/releases.json | jq -r ".[\"$version\"].version")
    if [ "$version" != "${semver%.*}" ]; then
        semver=$(curl -sL "$trunk"/archives/ | grep -Po '(?<=href=")[^"]*' | grep -Po "$version.[0-9]+" | sort -V | tail -1)
        trunk="$trunk"/archives
    fi
    curl -sL "$trunk" | grep -Po '(?<=href=")[^"]*' | grep -E "$semver" | xargs -n 1 -I{} curl -sLO $trunk/{}
)
