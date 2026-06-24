export USERNAME=$(whoami)
export UID=$(id -u)
export GID=$(id -g)
docker compose exec autoware_workspace zsh
