#!/bin/sh
echo "Creating mongodb admin user"
mongo --authenticationDatabase admin --host localhost -u "${DATABASE_USERNAME:-tldradmin}" -p "${DATABASE_PASSWORD:-rP8P5nw3nOjq7T7LBthBNlB8yKEnmT}" --eval \
"db.createUser({user: '${DATABASE_USERNAME:-tldradmin}', pwd: '${DATABASE_PASSWORD:-rP8P5nw3nOjq7T7LBthBNlB8yKEnmT}', roles: [ { role: 'userAdminAnyDatabase', db: 'admin' }, { role: 'readWriteAnyDatabase', db: 'admin' } ]})"