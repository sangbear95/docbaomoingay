# Đọc báo mỗi ngày

Trang tổng hợp tin từ **VnExpress**, **Tuổi Trẻ** và **Thanh Niên**, chia theo chuyên mục (Thời sự, Thế giới, Kinh tế, Thể thao, Giải trí, Pháp luật, Giáo dục, Sức khỏe, Công nghệ), tự cập nhật mỗi 30 phút.

Trang web: https://sangbear95.github.io/docbaomoingay/

## Cách hoạt động

1. `build.py` đọc RSS "tin mới nhất" và RSS từng chuyên mục của các báo, gộp lại (bài nằm ở nhiều chuyên mục chỉ hiện một lần), sắp xếp theo thời gian và tạo file `site/index.html`.
2. `summarize.py` tải các bài mới và chọn ra vài câu tóm tắt.
3. GitHub Actions (`.github/workflows/pages.yml`) chạy script mỗi 30 phút rồi đăng trang lên GitHub Pages.

Trang chỉ hiện tiêu đề, tóm tắt, ảnh và link. Bấm vào tin sẽ mở bài gốc trên trang báo.

## Tóm tắt

Mỗi tin có hai nút, đều miễn phí và không cần khóa API:

- **Tóm tắt nhanh**: 3 câu quan trọng nhất trong bài, hiện ngay dưới tin. `summarize.py` làm sẵn lúc cập nhật trang: tải bài gốc, tìm phần thân bài, chấm điểm từng câu (từ khóa lặp lại nhiều, câu ở đầu bài, câu có số liệu) rồi chọn câu điểm cao nhất. Đây là trích câu có sẵn, không phải AI viết lại. Bài đã tóm tắt được lưu trong `cache/` (qua GitHub Actions cache) nên mỗi lần chỉ tải bài mới.
- **Hỏi Claude ↗**: mở claude.ai với câu hỏi tóm tắt bài đó, dùng tài khoản Claude.ai của bạn. Câu hỏi cũng được chép vào bộ nhớ tạm; nếu ô chat còn trống thì dán vào rồi gửi. Claude cần được bật tính năng tìm kiếm web để mở được link bài.

## Bật GitHub Pages (làm một lần)

Vào **Settings → Pages → Build and deployment → Source**, chọn **GitHub Actions**.
Sau đó vào tab **Actions → Cập nhật trang tin → Run workflow** để chạy lần đầu.

## Chạy trên máy

```bash
python3 build.py
```

Sau đó mở file `site/index.html` bằng trình duyệt. Không cần cài thư viện, chỉ cần Python 3.9 trở lên.

## Thêm hoặc bớt báo, chuyên mục

- Danh sách chuyên mục chung nằm ở `CATEGORIES` đầu file `build.py`.
- Mỗi báo trong `SOURCES` có link RSS tin mới nhất (`latest`) và link RSS cho từng chuyên mục (`categories`). Một chuyên mục có thể ghi nhiều link dự phòng; script dùng link đầu tiên đọc được.
- Link nào không đọc được sẽ hiện trong log của GitHub Actions, dạng `Tuổi Trẻ / Công nghệ: LỖI - ...`.
