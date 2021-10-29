/usr/local/bin/certbot certonly \
  --non-interactive \
  --agree-tos \
  --email {{ certbot_email }} \
  --preferred-challenges dns \
  --authenticator dns-duckdns \
  --dns-duckdns-token {{ duckdns_token }} \
  --dns-duckdns-propagation-seconds 60 \
  -d "{{ duckdns_domain }}.duckdns.org"
