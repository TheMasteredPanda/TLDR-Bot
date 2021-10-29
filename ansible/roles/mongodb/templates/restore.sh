#!/bin/bash
mongorestore --gzip --archive="$(ls | grep "_backup.gz" | tail -n 1)" --authenticationDatabase=admin --host=localhost:27017 -u={{ database_username }} -p={{ database_password }} --drop
