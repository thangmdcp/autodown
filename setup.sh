#!/usr/bin/env bash
# setup.sh — Chạy 1 lần duy nhất trên VPS Hostinger mới
# Cách dùng: ssh root@<IP> "bash -s" < setup.sh
set -e

APP_DIR="/var/www/autodown"
DOMAIN=""   # ← điền domain của bạn vào đây, hoặc để trống nếu chỉ dùng IP

echo "==> Cập nhật hệ thống..."
apt-get update -q && apt-get upgrade -y -q

echo "==> Cài Python, ffmpeg, nginx..."
apt-get install -y -q python3 python3-pip python3-venv ffmpeg nginx

echo "==> Tạo thư mục app..."
mkdir -p "$APP_DIR"
useradd -r -s /bin/false autodown 2>/dev/null || true

echo "==> Tạo virtualenv & cài packages..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q flask yt-dlp gunicorn

echo "==> Tạo systemd service..."
cat > /etc/systemd/system/autodown.service << 'EOF'
[Unit]
Description=AutoDown
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/autodown
Environment="PATH=/var/www/autodown/venv/bin"
ExecStart=/var/www/autodown/venv/bin/gunicorn \
    --workers 2 \
    --bind unix:/run/autodown.sock \
    --timeout 300 \
    --log-file /var/log/autodown.log \
    app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

echo "==> Cấu hình Nginx..."
cat > /etc/nginx/sites-available/autodown << EOF
server {
    listen 80;
    server_name ${DOMAIN:-_};

    client_max_body_size 10M;

    location / {
        proxy_pass http://unix:/run/autodown.sock;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
EOF

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/autodown /etc/nginx/sites-enabled/

nginx -t && systemctl restart nginx

systemctl daemon-reload
systemctl enable autodown

echo ""
echo "✅ Setup xong! Giờ chạy ./deploy.sh từ máy Mac để upload code."
echo ""
if [ -n "$DOMAIN" ]; then
    echo "   Gắn domain xong thì chạy thêm:"
    echo "   apt install -y certbot python3-certbot-nginx"
    echo "   certbot --nginx -d $DOMAIN"
fi
