#!/bin/bash
cd "$(dirname "$0")"

VENV_PY="venv/bin/python"

# Cài venv lần đầu nếu chưa có.
if [ ! -f "$VENV_PY" ]; then
    echo "Cai dat lan dau (chi xay ra 1 lan)..."
    python3 -m venv venv
    venv/bin/pip install --quiet --upgrade pip
    venv/bin/pip install --quiet -r requirements.txt
    echo "Xong."
fi

# Cài ffmpeg qua Homebrew nếu chưa có (cho phép tải độ phân giải cao nhất).
if ! command -v ffmpeg &>/dev/null; then
    if command -v brew &>/dev/null; then
        echo "Cai ffmpeg de tai chat luong cao nhat (chi 1 lan)..."
        brew install ffmpeg --quiet
    else
        echo "[INFO] Chua co ffmpeg - app van chay nhung chi tai H.264 stream."
        echo "       De tai do phan giai cao nhat, cai Homebrew truoc:"
        echo "       /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        echo "       Sau do chay: brew install ffmpeg"
    fi
fi

exec "$VENV_PY" app.py
