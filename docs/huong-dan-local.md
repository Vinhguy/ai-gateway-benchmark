# Chạy benchmark trên máy local Windows

Tài liệu này dành cho máy Windows chạy load generator. Gateway và mock provider chạy trong Linux VM trên server; máy local phát HTTP request bằng Python asyncio/aiohttp.

## Workload chuẩn

- 5.000 virtual user (VU) là số worker mô phỏng người dùng, không phải request/giây.
- Tối đa 1.000 request in-flight tại một thời điểm.
- Burst gửi đúng 1.000 request đồng thời; sustained chạy 10 phút với 5.000 VU, tối đa 1.000 in-flight và think time 2–5 giây.
- Generator giới hạn 8 GB RAM và 8 CPU equivalents; tự dừng nếu RAM trống trên máy thấp hơn 2 GiB. Giữ 5 GB cho các tác vụ khác.

RPS là số response hoàn thành trong cửa sổ đo; không đồng nghĩa với số VU hay giới hạn in-flight.

## 1. Clone và cài đặt

Mở PowerShell:

```powershell
git clone --branch benchmark-setup --recurse-submodules https://github.com/Vinhguy/ai-gateway-benchmark.git
cd ai-gateway-benchmark\client
python --version
```

Cần Python 3.12 x64. Nếu repo đã clone mà thiếu nội dung submodule, chạy `git submodule update --init --recursive` từ thư mục gốc repo.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

Chạy các lệnh benchmark từ `client/`. Kết quả nằm trong `results/` ở thư mục gốc repo và mặc định bị Git ignore.

## 2. Kiểm tra server

Hoàn tất [runbook server](huong-dan-server-ai.md), để các monitor/guard trên server hoạt động và khởi động gateway cần đo. Thay `<SERVER_PRIVATE_IP>` bằng IP private của Linux VM:

```powershell
Test-NetConnection <SERVER_PRIVATE_IP> -Port 8080 # Bifrost
Test-NetConnection <SERVER_PRIVATE_IP> -Port 4000 # LiteLLM
```

Chỉ port của gateway đang đo được phép truy cập từ IP máy local. Port 8000 của mock provider phải ở lại nội bộ Compose.

## 3. Burst: 1.000 request đồng thời

Khi Bifrost đã chạy trên server:

```powershell
$id = "bifrost-burst-$(Get-Date -Format yyyyMMdd-HHmmss)"
.\run.ps1 `
  -TargetUrl "http://<SERVER_PRIVATE_IP>:8080/v1/chat/completions" `
  -Gateway bifrost -VuCount 5000 -MaxInFlight 1000 `
  -Profile burst -BurstCount 1000 -RunId $id
```

Sau khi kết thúc, generator ghi `results/<run-id>.json` và `results/<run-id>-client-resources.csv`. File `results/<run-id>-abort.json` chỉ xuất hiện nếu run bị dừng bất thường.

## 4. Sustained: 10 phút

```powershell
$id = "bifrost-sustained-$(Get-Date -Format yyyyMMdd-HHmmss)"
.\run.ps1 `
  -TargetUrl "http://<SERVER_PRIVATE_IP>:8080/v1/chat/completions" `
  -Gateway bifrost -VuCount 5000 -MaxInFlight 1000 `
  -Profile sustained -DurationSeconds 600 -RunId $id
```

Đối với LiteLLM, dùng `-Gateway litellm` và port `4000`. Chạy hai gateway tuần tự, với cùng profile/thông số và RunId riêng cho từng run. Không chạy song song.

## 5. Validate

Server cần tạo Linux guest CSV và Windows host CSV bằng cùng RunId. Copy các CSV sang máy local qua kênh nội bộ được chấp thuận. Từ `client/` chạy:

```powershell
.\.venv\Scripts\python.exe .\report.py `
  ..\results\$id.json `
  --client-resources ..\results\$id-client-resources.csv `
  --server-resources <PATH_TO_SERVER_LINUX_CSV> `
  --server-host-resources <PATH_TO_SERVER_WINDOWS_HOST_CSV> `
  --abort-event ..\results\$id-abort.json
```

Nếu không có abort file, bỏ `--abort-event` và đường dẫn tương ứng. Validator tạo `*-validation.json` và trả mã khác 0 nếu thiếu bằng chứng tải/tài nguyên hoặc không đạt ngưỡng. Chỉ so sánh run đã validate.

## Xử lý lỗi

- Thiếu `TargetUrl`: truyền URL đầy đủ gồm `/v1/chat/completions`.
- Không kết nối được: kiểm tra IP/route, gateway, firewall và port đúng.
- Run dừng do RAM: đóng tác vụ nền, chạy lại bằng RunId mới; không tắt guard hay nâng giới hạn.
- Validation báo concurrency thấp, thiếu mẫu, hoặc invalid: không dùng run đó để so sánh; giữ artifacts để kiểm tra.
- Không lưu API key riêng vào Git. Test keys mặc định đã khớp Compose; chỉ cấu hình key riêng qua biến môi trường của PowerShell nếu gateway được thay đổi.
