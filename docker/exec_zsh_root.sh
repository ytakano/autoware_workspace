export USERNAME=$(whoami)
export UID=$(id -u)
export GID=$(id -g)
docker compose exec -u root autoware_workspace zsh
