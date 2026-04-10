server {
    listen 80 default_server;
    listen 443 ssl;
    listen [::]:443 ssl;
    include snippets/self-signed.conf;
 #   location/59580/ {
    location/<portnumber>/
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Host $http_host;
#       proxy_pass 'http://127.0.0.1:59580/proxy/8443'        
#       proxy_pass 'http://127.0.0.1:8443';
        proxy_pass 'http://127.0.0.1:<portnumber>';
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Long-lived connection timeout
        proxy_connect_timeout 7d;
        proxy_read_timeout 7d;
        proxy_sent_timeout 7d;

        # Disable buffering for real-time data
        proxy_buffering off;
        proxy_request_buffering off;


    }
}