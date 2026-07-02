# FB Downloader

Web app chạy trên **localhost** để tải video/reel Facebook (công khai hoặc của chính bạn) và tự động đặt tên file theo caption của bài đăng. Có giao diện trực quan: nhập link, xem tiến trình tải theo thời gian thực, và bảng trạng thái (caption, % tải, thành công/thất bại, link tải file). Không hỗ trợ bypass đăng nhập/CAPTCHA.

## Cách dễ nhất: double-click để chạy (macOS)

Double-click file **`Launch FB Downloader.command`** trong Finder. Lần chạy đầu tiên nó tự tạo môi trường Python (`venv`) và cài `yt-dlp` + `flask`, sau đó khởi động server và tự mở trình duyệt tại `http://localhost:5000`.

> Nếu macOS chặn vì "unidentified developer": chuột phải vào file → Open → xác nhận Open lại.
> Đóng cửa sổ Terminal đó để tắt server.

## Cài đặt thủ công

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Mở trình duyệt tại **http://localhost:5000** (server tự mở trình duyệt khi chạy `python app.py` trực tiếp).

## Sử dụng giao diện web

1. Chọn chế độ: **Tải 1 video** hoặc **Tải nhiều video** (dán danh sách link, mỗi dòng 1 link).
2. (Tuỳ chọn) Nhập thư mục lưu — mặc định `./downloads`.
3. (Tuỳ chọn) Chọn file `cookies.txt` nếu video cần đăng nhập.
4. Bấm **Bắt đầu tải**. Bảng "Trạng thái tải" hiện ngay bên dưới, cập nhật theo thời gian thực:
   - **Caption** của bài đăng (và link gốc).
   - **Tiến trình** tải (% + tốc độ + thời gian còn lại).
   - **Trạng thái**: Đang chờ / Lấy thông tin / Đang tải / Thành công / Thất bại (kèm lý do lỗi).
   - **File**: link tải file về máy khi hoàn tất.

## Video riêng tư / cần đăng nhập

Nếu video báo lỗi cần đăng nhập:

1. Cài extension **"Get cookies.txt"** trên Chrome.
2. Đăng nhập Facebook trên trình duyệt, mở trang video cần tải.
3. Dùng extension để xuất cookie ra file `cookies.txt`.
4. Chọn file đó ở ô "Cookie" trên giao diện web rồi tải lại.

## Lỗi do yt-dlp cũ

Facebook thường xuyên thay đổi cấu trúc trang, khiến yt-dlp cũ bị lỗi trích xuất ("Unable to extract..."). Cập nhật:

```bash
pip install -U yt-dlp
```

## Cách đặt tên file

- Lấy khoảng 70 ký tự đầu của caption (description) bài đăng.
- Loại bỏ ký tự không hợp lệ cho tên file (`/ \ : * ? " < > |`, xuống dòng...) và emoji.
- Nếu caption rỗng, dùng ID video làm tên file (`facebook_video_<id>`).
- Nếu tên file trùng, tự động thêm hậu tố `_1`, `_2`, ...

## Dùng qua dòng lệnh (CLI, tuỳ chọn)

Vẫn có thể dùng CLI gốc nếu muốn dùng trong script/tự động hoá:

```bash
python fb_downloader.py "https://www.facebook.com/watch/?v=123456789"
python fb_downloader.py --batch links.txt --output-dir ./downloads
python fb_downloader.py "URL" --cookies cookies.txt
```

CLI in bảng trạng thái tương tự giao diện web ngay trên terminal, và với `--batch` còn ghi log vào `downloads/batch_log.txt`.

## Cấu trúc project

- `app.py` — web server (Flask), API `/api/submit`, `/api/status/<id>`, `/api/download/<id>/<index>`.
- `core.py` — logic dùng chung: gọi yt-dlp Python API, sanitize tên file, xử lý lỗi.
- `fb_downloader.py` — CLI dùng chung `core.py`.
- `templates/index.html`, `static/css/style.css`, `static/js/app.js` — giao diện web.
- `Launch FB Downloader.command` — double-click để chạy web app (macOS).
