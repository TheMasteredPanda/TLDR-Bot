This is a simple guide to the ansible workings of the tldrbot. \
All of this is designed to run on linux and wont run on anythin else.
___
### Requirements
* ansible >= 2.11.6
* python >= 3.9
* jinja >= 3.0.2
___
### Run the playbook
The playbook needs to be run in the same directory as the infra.yaml file.
```shell
ansible-playbook infra.yaml --vault-password-file /path/to/vault/password/file
```
___
### Hosts
the hosts are seperated into 3 groups
* tldrbot -> Runs the bot, the api and the [image processor](https://github.com/Hattyot/image_processor)
* database -> Runs the database for the bot

On the main instance they're all run on the same server, but it was designed so that they are easy to separate.
___
### Playbook
The playbook is separated into 3 plays
* init -> roles that need to be given to all hosts
* tldrbot -> roles associated with the tldrbot server
* database -> roles associated with the database
___
### Roles
* Docker -> installs docker and creates tldr-net network for docker
* duckdns -> installs duckdns
  * Files:
    * duckdns.sh -> shell script run by cron that keeps the duckdns domain ip updated
* image_processor -> sets up the image-processor docker-container 
* init -> sets up automatic apt cache updates
* lets_encrypt -> installs letsencrypt and creates a cert for the duckdns domain
    * Files:
        * certbot.sh -> shell script used to create the certs for the duckdns domain
* mongodb -> sets up mongodb container
    * Files:
        * backup.sh -> shell script used to create dump of the database
        * restore.sh -> shell script that takes the latest dump and uses it to restore the database contents
* python -> installs python (3.9) and pip (3.9)
* tldrbot -> sets up the tldr-bot container
    * Files:
        * service_account.json -> encrypted google drive api service account json authentication file
* tldrbot_user -> creates the tldrbot user and its home directory
* cleanup -> Does a bit of cleanup after running all the other roles
___
### Group vars
* tldrbot_repo -> Link to the tldrbot repository, in case a fork needs to be used
* image_processor_repo -> Link to the image processor repository, in case a fork needs to be used
* duckdns_domain -> the duckdns domain, `tldrcommunity` on the main instance
* duckdns_token -> token used for authenticating with duckdns to update the ip
* certbot_email -> email for certbot to notify you about the certs expiring
* database_username -> mongodb database username used to set up authentication for the bot
* database_password -> mongodb database password used to set up authentication for the bot
___
### SSH
Files used to easily give ssh access to the database and the bot
* database_authorized_keys -> list of ssh public keys for connecting to the database user
* tldrbot_authorized_keys -> list of ssh public keys for connecting to the bot user
___
### ENV
The main ansible directory contains an encrypted env file that contains the configuration for the bot. \
All the needed env variables can be seen in the main README.md
___
### Encrypt and Decrypt
Encrypt strings
```bash
ansible-vault encrypt_string important_string 123 --vault-password-file vault_password_file
```
Encrypt files
```bash
ansible-vault encrypt .env --vault-password-file vault_password_file
```

Decrypt
```bash
ansible-vault decrypt .env --vault-password-file vault_password_file
```
___