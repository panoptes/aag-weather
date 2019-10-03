#!/bin/bash -ie

USER_ID=${LOCAL_USER_ID:-9001}

# See https://denibertovic.com/posts/handling-permissions-with-docker-volumes/
echo "Starting with UID : $USER_ID"
useradd --shell /bin/zsh -u $USER_ID -o -c "" -m aag
export HOME=/home/aag

# Update home permissions
chown -R ${USER_ID}:${USER_ID} $HOME

# Pass arguments
exec gosu aag "$@"
