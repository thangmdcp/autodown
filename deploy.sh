#!/usr/bin/env bash
# deploy.sh — Chạy từ máy Mac để upload code lên VPS và restart app
# Cách dùng: ./deploy.sh
set -e

# ── Cấu hình (sửa 2 dòng này) ────────────────────────────────────────────────
VPS_IP="123.456.789.0"      # ← IP VPS Hostinger của bạn
VPS_USER="root"             # ← user SSH (thường là root)
# ─────────────────────────────────────────────────────────────────────────────

APP_DIR="/var/www/autodown"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

# Những file/thư mục cần upload (bỏ venv, downloads, cache, script setup)
INCLUDE=(
    app.py
    core.py
    requirements.txt
    templates
    static
)

echo "==> Upload code lên $VPS_USER@$VPS_IP..."
rsync -avz --delete \
    $(printf -- "--include='%s' " "${INCLUDE[@]}") \
    --include='templates/***' \
    --include='static/***' \
    --exclude='*' \
    "$LOCAL_DIR/" \
    "$VPS_USER@$VPS_IP:$APP_DIR/"

echo "==> Cài packages mới (nếu có)..."
ssh "$VPS_USER@$VPS_IP" "
    source $APP_DIR/venv/bin/activate
    pip install -q -r $APP_DIR/requirements.txt
    chown -R www-data:www-data $APP_DIR
    systemctl restart autodown
    systemctl status autodown --no-pager -l
"

echo ""
echo "✅ Deploy xong!"
