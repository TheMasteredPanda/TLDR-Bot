#!/bin/bash

# create name for dump file
backup_dir=$(date +%Y-%m-%d_%H:%M)_backup.gz

# create dump
sudo mongodump --authenticationDatabase admin --username {{ database_username }} --password {{ database_password }} --gzip --archive=/home/tldrbot/mongodb/_backup.gz --db TLDR

# filename
sudo mv /home/tldrbot/mongodb/_backup.gz /home/tldrbot/mongodb/${backup_dir}

echo 'Backup complete'