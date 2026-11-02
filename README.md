# Đọc báo mỗi ngày

Trang tổng hợp tin mới nhất từ **VnExpress**, **Tuổi Trẻ** và **Thanh Niên**, tự cập nhật mỗi 30 phút.

Trang web: https://sangbear95.github.io/docbaomoingay/

## Cách hoạt động

1. `build.py` đọc RSS của các báo, gộp lại, bỏ bài trùng, sắp xếp theo thời gian và tạo file `site/index.html`.
2. GitHub Actions (`.github/workflows/pages.yml`) chạy script mỗi 30 phút rồi đăng trang lên GitHub Pages.

Trang chỉ hiện tiêu đề, tóm tắt, ảnh và link. Bấm vào tin sẽ mở bài gốc trên trang báo.

## Bật GitHub Pages (làm một lần)

Vào **Settings → Pages → Build and deployment → Source**, chọn **GitHub Actions**.
Sau đó vào tab **Actions → Cập nhật trang tin → Run workflow** để chạy lần đầu.

## Chạy trên máy

```bash
python3 build.py
```

Sau đó mở file `site/index.html` bằng trình duyệt. Không cần cài thư viện, chỉ cần Python 3.9 trở lên.

## Thêm hoặc bớt báo

Sửa danh sách `SOURCES` ở đầu file `build.py`, mỗi dòng gồm tên báo, mã ngắn, link RSS và màu nhận diện.
