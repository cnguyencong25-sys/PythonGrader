# Python Grader

Ứng dụng Flask quản lý bài tập Python, bài thi, chấm tự động và kết quả sinh viên.

## Luồng làm bài thi

1. Giáo viên vào **Quản lý bài kiểm tra**, tạo bài thi, đặt mật khẩu, thời gian, thời lượng và số lượt tối đa.
2. Trong cấu hình, giáo viên chọn câu hỏi hoặc số câu ngẫu nhiên theo chương. Đường link tham gia không hiển thị trên trang cấu hình.
3. Sinh viên đăng nhập, mở **Bài kiểm tra** và chọn **Vào thi**. Nếu bài thi đã đặt mật khẩu, hệ thống yêu cầu nhập mật khẩu và chỉ bắt đầu/khôi phục phiên khi mật khẩu đúng.
4. Phiên làm bài được lưu trên server. Khi kết thúc hoặc hết giờ, hệ thống chấm bài; bài đã nộp chỉ có thể xem lại ở chế độ chỉ đọc.
5. Giáo viên xem bảng điểm, lọc theo ngày/lớp/MSV/họ tên, xem code, điểm từng câu và số lần rời màn hình thi.

Mật khẩu được lưu dưới dạng hash và kiểm tra ở server trước khi tạo phiên. Mật khẩu chỉ có hiệu lực từ giờ bắt đầu. Luồng thi công khai cũ tại `/exam/<access_code>` vẫn được hỗ trợ nếu sử dụng URL truy cập trực tiếp.

## Quản lý sinh viên

Giáo viên mở **Quản lý sinh viên** để tìm kiếm tất cả tài khoản sinh viên. Trang lịch sử hiển thị các lượt làm những bài thi do giáo viên hiện tại tạo, gồm điểm, trạng thái, thời gian và mã nguồn đã lưu. Giáo viên có thể cấp một lượt làm lại mới; lịch sử và mã nguồn cũ được giữ lại. Xóa tài khoản sẽ xóa các phiên luyện tập, bài thi và phiên đăng nhập gắn trực tiếp với tài khoản đó.

Các phiên thi công khai chỉ lưu MSV dạng văn bản và không liên kết với tài khoản sinh viên; vì vậy chúng không xuất hiện trong lịch sử tài khoản và không bị xóa cùng tài khoản.

Giao diện sinh viên hỗ trợ chuyển giữa chế độ sáng và tối; tùy chọn được lưu trên trình duyệt và dùng chung giữa các trang làm bài.

## Múi giờ

Giờ lịch thi và phiên thi được lưu theo giờ Việt Nam; thời gian luyện tập và hoạt động hệ thống được lưu theo UTC. API trả timestamp kèm offset rõ ràng, còn giao diện giáo viên và sinh viên luôn hiển thị theo `Asia/Ho_Chi_Minh`. Khi khởi động, ứng dụng tự chuẩn hóa thời điểm kết thúc phiên thi cũ bị lưu theo UTC trong khi thời điểm bắt đầu dùng giờ Việt Nam.

## Hồ sơ sinh viên

Sinh viên mở **Thông tin sinh viên** để cập nhật họ tên, MSV và lớp; email đăng nhập chỉ đọc. Mật khẩu hiện tại không được hiển thị. Khi đổi mật khẩu, sinh viên cần xác nhận mật khẩu cũ và nhập mật khẩu mới hai lần; mật khẩu mới phải có ít nhất 8 ký tự và không vượt quá giới hạn 72 byte của bcrypt.

## Google Sheets

Tại trang **Quản lý điểm** của từng bài thi, nút **Xuất báo cáo xếp hạng** tạo một Google Sheet mới và mở liên kết kết quả. Báo cáo dùng các bộ lọc đang chọn, xếp theo điểm giảm dần, thời gian nộp sớm hơn, số vi phạm ít hơn; bao gồm hạng, thông tin sinh viên, email, điểm, thời gian nộp, vi phạm, trạng thái và thống kê tổng quan. Điểm hòa vẫn được đánh số hạng tuần tự theo yêu cầu.

Tính năng gọi Google Apps Script Web App; tạo script dưới đây trong tài khoản Google có quyền tạo Sheet:

```javascript
function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    const report = data.report;
    const title = `${report.exam_name} - Bảng điểm xếp hạng`;
    const spreadsheet = SpreadsheetApp.create(title);
    const sheet = spreadsheet.getSheets()[0];
    sheet.setName("Bảng xếp hạng");
    sheet.getRange("A1:B5").setValues([
      ["BÁO CÁO KẾT QUẢ BÀI THI", report.exam_name],
      ["Thời gian làm bài", `${report.duration_minutes} phút`],
      ["Ngày xuất báo cáo", report.exported_at],
      ["Tổng số sinh viên", report.participant_count],
      ["Điểm trung bình / Cao nhất / Thấp nhất",
        `${report.average_score ?? "—"} / ${report.highest_score ?? "—"} / ${report.lowest_score ?? "—"}`],
    ]);

    const headers = [
      "Xếp hạng", "Mã sinh viên", "Họ và tên", "Lớp", "Email",
      "Điểm tổng", "Thời gian nộp bài", "Số lần vi phạm", "Trạng thái",
    ];
    sheet.getRange(7, 1, 1, headers.length).setValues([headers]);
    if (data.scores.length) {
      const rows = data.scores.map(item => [
        item.rank, item.student_id, item.full_name, item.class_name, item.email,
        `${item.score} / ${item.max_score}`, item.finished_at,
        item.violation_count, item.status,
      ]);
      sheet.getRange(8, 1, rows.length, headers.length).setValues(rows);
      sheet.getRange(7, 1, rows.length + 1, headers.length)
        .setBorder(true, true, true, true, true, true);
    }

    sheet.getRange("A1:B1").setFontSize(13).setFontWeight("bold")
      .setBackground("#e8f3ee");
    sheet.getRange(7, 1, 1, headers.length).setFontWeight("bold")
      .setBackground("#16714b").setFontColor("#ffffff").setWrap(true);
    sheet.getRange("A1:B5").setVerticalAlignment("middle");
    sheet.setFrozenRows(7);
    sheet.autoResizeColumns(1, headers.length);
    sheet.setColumnWidth(3, 210);
    sheet.setColumnWidth(5, 220);
    sheet.setColumnWidth(7, 190);
    sheet.setColumnWidth(9, 200);

    return ContentService.createTextOutput(JSON.stringify({
      success: true,
      spreadsheetUrl: spreadsheet.getUrl(),
    })).setMimeType(ContentService.MimeType.JSON);
  } catch (error) {
    return ContentService.createTextOutput(JSON.stringify({
      success: false,
      message: "Không thể tạo báo cáo Google Sheets.",
    })).setMimeType(ContentService.MimeType.JSON);
  }
}
```

Deploy Apps Script thành **Web app**, chọn **Execute as: Me** và cấp quyền truy cập phù hợp để máy chủ gọi endpoint; sau đó cấu hình URL triển khai trong `.env`:

```text
GOOGLE_SHEETS_WEBHOOK_URL=https://script.google.com/macros/s/DEPLOYMENT_ID/exec
```

Script cần trả JSON có `success: true` và `spreadsheetUrl` (hoặc `url`). Giữ URL webhook bí mật và chỉ cấu hình trên máy chủ; không đưa URL vào giao diện hoặc mã nguồn. Nếu chưa cấu hình, nút xuất sẽ báo thiếu `GOOGLE_SHEETS_WEBHOOK_URL`.
Với bài thi công khai, hệ thống không thu thập email nên cột Email sẽ để trống; tài khoản sinh viên đăng nhập sẽ xuất đúng email đã đăng ký.

## Chạy và kiểm thử

### Chuẩn bị cấu hình riêng

Không đưa `.env`, cơ sở dữ liệu trong `instance/`, môi trường `.venv/` hoặc dữ liệu tải lên vào GitHub. Sao chép `.env.example` thành `.env` trên từng máy triển khai rồi điền thông tin riêng; không commit `.env`. Tạo `SECRET_KEY` và `JWT_SECRET_KEY` khác nhau, ngẫu nhiên và đủ dài; chỉ lưu URL Apps Script trong biến `GOOGLE_SHEETS_WEBHOOK_URL` của môi trường triển khai. Không dùng các giá trị mẫu trong `.env.example` cho môi trường thật.

```powershell
.\.venv\Scripts\python.exe app.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Đặt ứng dụng sau HTTPS khi triển khai thật. Bộ chấm hiện chạy chương trình Python bằng tiến trình con; triển khai thi có mã không tin cậy cần cô lập tiến trình chấm trong môi trường sandbox phù hợp.