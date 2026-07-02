#!/usr/bin/env python3
"""
fb_downloader.py — CLI tool (tuỳ chọn, dành cho script/tự động hoá).

Cách dùng thông thường: chạy web app thay thế.
  python app.py  →  mở http://localhost:5000

CLI:
  python fb_downloader.py "https://www.facebook.com/watch/?v=..."
  python fb_downloader.py --batch links.txt
  python fb_downloader.py "URL" --output-dir ./my_videos

Chỉ dùng cho video công khai hoặc video của chính bạn.
"""

import argparse
import os
import sys

try:
    import core
except ImportError:
    print("Lỗi: không tìm thấy core.py (phải ở cùng thư mục với fb_downloader.py)", file=sys.stderr)
    sys.exit(1)

try:
    import yt_dlp  # noqa: F401
except ImportError:
    print("Lỗi: chưa cài yt-dlp. Chạy: pip install -U yt-dlp", file=sys.stderr)
    sys.exit(1)


def cli_on_event():
    def handler(event):
        etype = event.get("type")
        if etype == "probing":
            print("  Đang lấy metadata...")
        elif etype == "caption":
            caption = event.get("caption") or event.get("video_id")
            print(f"  Caption: {(caption or '')[:80]}")
            print(f"  Tên file: {event.get('filename')}")
        elif etype == "progress":
            percent = event.get("percent")
            pct = f"{percent:5.1f}%" if percent is not None else "  ?  "
            speed = event.get("speed")
            spd = f"{speed / 1024 / 1024:.2f} MB/s" if speed else "-"
            eta = event.get("eta")
            eta_s = f"{eta}s" if eta is not None else "-"
            sys.stdout.write(f"\r  Đang tải... {pct}  tốc độ: {spd}  còn lại: {eta_s}   ")
            sys.stdout.flush()
            if percent == 100:
                sys.stdout.write("\n")
    return handler


def _truncate(text, width):
    text = (text or "").replace("\n", " ").strip()
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)].rstrip() + "…"


def print_status_table(rows):
    if not rows:
        return
    CAP_W, STAT_W, DETAIL_W = 45, 12, 40

    def line(c="-"):
        return "+" + c * 7 + "+" + c * (CAP_W + 2) + "+" + c * (STAT_W + 2) + "+" + c * (DETAIL_W + 2) + "+"

    print()
    print(line("="))
    print(f"| {'#':^5} | {'Caption':<{CAP_W}} | {'Trạng thái':<{STAT_W}} | {'File / Lỗi':<{DETAIL_W}} |")
    print(line("="))
    for idx, row in enumerate(rows, 1):
        caption = row.get("caption") or row.get("url") or "-"
        status = "Thành công" if row.get("status") else "Thất bại"
        detail = row.get("detail") or ""
        print(f"| {idx:^5} | {_truncate(caption, CAP_W):<{CAP_W}} | {status:<{STAT_W}} | {_truncate(detail, DETAIL_W):<{DETAIL_W}} |")
    print(line("="))
    total = len(rows)
    ok = sum(1 for r in rows if r.get("status"))
    print(f"Tổng: {total}  |  Thành công: {ok}  |  Thất bại: {total - ok}")


def run_batch(file_path, output_dir):
    if not os.path.isfile(file_path):
        print(f"Lỗi: không tìm thấy file: {file_path}", file=sys.stderr)
        sys.exit(1)

    with open(file_path, encoding="utf-8") as f:
        urls = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]

    if not urls:
        print("Lỗi: file không có link nào hợp lệ.", file=sys.stderr)
        sys.exit(1)

    results, table_rows = [], []
    for idx, url in enumerate(urls, 1):
        print(f"\n[{idx}/{len(urls)}] {url}")
        try:
            result = core.download_one(url, output_dir, on_event=cli_on_event())
            print(f"  Thành công: {result['path']}")
            results.append((url, True, result["path"]))
            table_rows.append({"caption": result["caption"], "url": url, "status": True, "detail": result["path"]})
        except ValueError as e:
            print(f"  Thất bại: {e}", file=sys.stderr)
            results.append((url, False, str(e)))
            table_rows.append({"caption": "", "url": url, "status": False, "detail": str(e)})
        except core.DownloadFailure as e:
            print(f"  Thất bại: {e}", file=sys.stderr)
            results.append((url, False, str(e)))
            table_rows.append({"caption": e.caption, "url": url, "status": False, "detail": str(e).splitlines()[0]})

    log_path = os.path.join(output_dir, "batch_log.txt")
    os.makedirs(output_dir, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        for url, ok, info in results:
            f.write(f"[{'OK' if ok else 'FAILED'}] {url} -> {info}\n")

    print_status_table(table_rows)
    ok_count = sum(1 for _, ok, _ in results if ok)
    print(f"\nHoàn tất: {ok_count}/{len(results)} video tải thành công.")
    print(f"Log: {log_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Tải video Facebook và đặt tên file theo caption."
    )
    parser.add_argument("url", nargs="?", help="Link video Facebook")
    parser.add_argument("--output-dir", default="./downloads", help="Thư mục lưu (mặc định: ./downloads)")
    parser.add_argument("--batch", default=None, help="File .txt chứa danh sách link (mỗi dòng 1 link)")
    args = parser.parse_args()

    if not args.url and not args.batch:
        parser.error("Cần cung cấp URL hoặc --batch <file.txt>")

    if args.batch:
        run_batch(args.batch, args.output_dir)
        return

    print(f"Đang xử lý: {args.url}")
    try:
        result = core.download_one(args.url, args.output_dir, on_event=cli_on_event())
    except ValueError as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        print_status_table([{"caption": "", "url": args.url, "status": False, "detail": str(e)}])
        sys.exit(1)
    except core.DownloadFailure as e:
        print(str(e), file=sys.stderr)
        print_status_table([{"caption": e.caption, "url": args.url, "status": False, "detail": str(e).splitlines()[0]}])
        sys.exit(1)

    print(f"\nĐã lưu tại: {result['path']}")
    print_status_table([{"caption": result["caption"], "url": args.url, "status": True, "detail": result["path"]}])


if __name__ == "__main__":
    main()
