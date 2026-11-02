# Đọc báo mỗi ngày

Trang tổng hợp tin mới nhất từ **VnExpress**, **Tuổi Trẻ** và **Thanh Niên**, tự cập nhật mỗi 30 phút.

Trang web: https://sangbear95.github.io/docbaomoingay/

## Cách hoạt động

1. `build.py` đọc RSS của các báo, gộp lại, bỏ bài trùng, sắp xếp theo thời gian và tạo file `site/index.html`.
2. GitHub Actions (`.github/workflows/pages.yml`) chạy script mỗi 30 phút rồi đăng trang lên GitHub Pages.

Trang chỉ hiện tiêu đề, tóm tắt, ảnh và link. Bấm vào tin sẽ mở bài gốc trên trang báo.

## Tóm tắt bằng AI

Mỗi tin có nút **✦ Tóm tắt AI**. Khi bấm, Claude mở bài gốc, đọc toàn văn rồi viết tóm tắt bằng tiếng Việt: một câu ý chính và 3–5 gạch đầu dòng.

- Cần khóa API của Claude. Tạo khóa tại https://platform.claude.com/settings/keys và nạp tiền vào tài khoản.
- Lần đầu bấm nút, trang sẽ hỏi khóa. Khóa chỉ lưu trong trình duyệt của bạn (localStorage), không nằm trong mã nguồn hay trên GitHub. Muốn đổi hoặc xóa khóa, bấm **Khóa AI** ở đầu trang.
- Mỗi bài đã tóm tắt được lưu lại trong trình duyệt, bấm lại không tốn thêm tiền.
- Mã gọi Claude nằm trong `static/summary.js`. Model dùng là `claude-opus-5-5`, có thể đổi ở biến `MODEL`.

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
