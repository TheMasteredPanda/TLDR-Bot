#!/bin/sh
echo "Creating mongodb admin user"
mongo --authenticationDatabase admin --host localhost -u "${DATABASE_USERNAME}" -p "${DATABASE_PASSWORD}" --eval \
"db.createUser({user: '${DATABASE_USERNAME}', pwd: '${DATABASE_PASSWORD}', roles: [ { role: 'userAdminAnyDatabase', db: 'admin' }, { role: 'readWriteAnyDatabase', db: 'admin' } ]})"