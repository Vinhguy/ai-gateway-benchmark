# Runbook cài benchmark trên Windows Server (cho AI agent)

Dùng tài liệu này để AI agent có quyền thao tác chuẩn bị gateway benchmark. Windows Server là host; Bifrost/LiteLLM và mock provider chạy trong Linux VM Hyper-V có giới hạn tài nguyên. Không cài Docker Desktop lên Windows Server.

## Mục tiêu và giới hạn

- Host: Windows Server, RAM 16 GB, Xeon Gold 6130; chừa 5 GB cho tác vụ khác. Host monitor tắt VM nếu RAM trống dưới 2 GiB.
- Linux VM: tối đa 8 GiB RAM và 9 vCPU.
- Mocker: tối đa 1 GiB RAM / 1 CPU. Gateway đang đo: tối đa 6 GiB RAM / 8 CPU. Chừa khoảng 1 GiB guest overhead.
- Chỉ chạy một gateway tại một thời điểm. Mocker latency bằng 0 và chỉ truy cập trong Docker network.
- Chỉ mở TCP 8080 (Bifrost) hoặc 4000 (LiteLLM) từ IP private của máy local. Không mở port 8000.
- Load generator chạy trên máy local, không chạy trên server.

## Chỉ dẫn cho AI agent

1. Kiểm tra hiện trạng trước khi cài. Không xóa hay ghi đè VM, switch, disk, repo, firewall rule có sẵn. Nếu VM `AI-Benchmark` tồn tại mà không rõ thuộc benchmark, dừng và báo người vận hành.
2. Làm từng bước, ghi lại lệnh và kết quả. Xin người vận hành hỗ trợ khi thiếu credential, cần reboot, chưa rõ lựa chọn mạng, hoặc thao tác có thể ảnh hưởng workload khác.
3. Không in secret vào log hoặc commit `.env`. Repo dùng key test, không cần API key dịch vụ thật.
4. Chưa biết IP máy local thì chưa tạo inbound firewall rule. Không mở port cho `Any` hoặc Internet.
5. Không cho bắt đầu tải cho đến khi cả host guard, guest guard và sampler đã chạy.

## A. Preflight Windows Server

Mở PowerShell **Run as Administrator** và ghi nhận:

```powershell
Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsArchitecture
Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize, FreePhysicalMemory
Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, VirtualizationFirmwareEnabled
Get-WindowsFeature Hyper-V, Hyper-V-PowerShell
Get-VMSwitch | Select-Object Name, SwitchType
Get-VM | Select-Object Name, State, MemoryMaximum, ProcessorCount
```

Tiếp tục khi Windows edition hỗ trợ Hyper-V, firmware virtualization bật, có switch phù hợp và còn ít nhất 2 GiB RAM. Ưu tiên switch hiện có đã được xác định. Không đổi NIC/bridge trên host đang chạy workload khác.

Nếu Hyper-V chưa cài và hệ điều hành hỗ trợ, cài role cùng PowerShell tools:

```powershell
Install-WindowsFeature -Name Hyper-V -IncludeManagementTools -Restart
```

Lệnh có thể reboot host. Nếu cần reboot, dừng và xin người vận hành chọn thời điểm; sau khi reboot, tiếp tục từ preflight. Không cài Docker Desktop.

## B. Linux VM và Docker

Dùng VM `AI-Benchmark` nếu đã xác định đúng VM của benchmark. Nếu chưa có, tạo VM mới với tên không xung đột, Linux x64 (Ubuntu Server LTS hoặc distro tương đương) và switch đã được chọn. Không tự tạo autoinstall từ image chưa được xác nhận. Nếu cài OS cần thao tác tương tác, hoặc cần credential guest, dừng tại đó và yêu cầu người vận hành hoàn tất/cung cấp quyền an toàn.

Khi VM đang tắt, đặt giới hạn:

```powershell
Set-VM -Name 'AI-Benchmark' -DynamicMemoryEnabled $true `
  -MemoryStartupBytes 6GB -MemoryMinimumBytes 4GB -MemoryMaximumBytes 8GB
Set-VMProcessor -VMName 'AI-Benchmark' -Count 9
```

Kết nối VM tới switch phù hợp, boot Linux, lấy IP private, và xác nhận SSH từ host. Cài Docker Engine và Compose v2 từ nguồn chính thức của distro/Docker, bật Docker service khi boot. Dùng `sudo docker` nếu chưa thiết lập quyền Docker cho operator. Kiểm tra trong Linux:

```bash
docker version
docker compose version
```

Không phơi SSH ra Internet. Nếu AI không có quyền truy cập guest, yêu cầu người vận hành thiết lập SSH/credential; không ghi mật khẩu vào lệnh hay tài liệu.

## C. Clone repo và cấu hình stack

Trong Linux guest:

```bash
git clone --branch benchmark-setup --recurse-submodules https://github.com/Vinhguy/ai-gateway-benchmark.git
cd ai-gateway-benchmark/server
cp .env.example .env
chmod 600 .env
docker compose --env-file .env -f compose.yaml config
```

Nếu repo đã tồn tại, từ thư mục gốc:

```bash
git checkout benchmark-setup
git pull --ff-only
git submodule update --init --recursive
```

Không commit `.env`, không thay bằng key dịch vụ thật. Ghi lại SHA repo và commit submodule để xác nhận hai gateway được đo bằng cùng cấu hình.

## D. Host guard và firewall

Trên Windows host, từ clone Windows của repo:

```powershell
cd <REPO_CLONE_ON_WINDOWS>\server
.\windows\Test-BenchmarkVm.ps1 -VmName 'AI-Benchmark'
```

Preflight phải đạt giới hạn 8 GiB, 9 vCPU, firmware virtualization bật và host còn ít nhất 2 GiB. Nếu không đạt, không chạy tải; giải phóng tài nguyên hoặc sửa VM khi đang tắt rồi kiểm tra lại.

Xác định private IP Linux VM và máy local trước khi mở port. Tạo Windows Firewall inbound rule giới hạn remote address là IP máy local, destination là VM/server theo cấu hình mạng, port là 8080 hoặc 4000 của gateway đang đo. Tạo rule ở firewall mạng ngoài nếu được yêu cầu. Không mở port 8000 hoặc gateway tới `Any`/Internet. Nếu không rõ mạng/firewall, dừng và nhờ quản trị mạng, không mở rộng rule.

## E. Khởi động gateway và monitors

Tạo RunId duy nhất (1–80 ký tự an toàn), ví dụ `bifrost-burst-20261013T120000`. Dùng đúng RunId đó ở host và Linux guest.

1. Windows host PowerShell: bật host RAM monitor trước benchmark; để cửa sổ mở:

   ```powershell
   .\windows\Watch-BenchmarkVm.ps1 -VmName 'AI-Benchmark' -RunId '<RUN_ID>'
   ```

   Nó ghi `server/results/<RUN_ID>-windows-host-resources.csv` và tắt VM nếu RAM host dưới 2 GiB.

2. Linux terminal thứ nhất: chọn đúng một gateway:

   ```bash
   cd <REPO_PATH>/server
   ./scripts/select-gateway.sh bifrost
   # Hoặc, cho run LiteLLM: ./scripts/select-gateway.sh litellm
   ```

   Selector kiểm tra RAM, dừng gateway cũ nếu đang chạy, rồi khởi động mocker và gateway đã chọn. Không dùng `docker compose up` trực tiếp để chuyển gateway.

3. Linux terminal thứ hai: bật guest memory guard và để cửa sổ mở:

   ```bash
   ./scripts/guard-server.sh monitor
   ```

   Nếu `MemAvailable` xuống dưới 2 GiB, guard dừng gateway rồi thoát lỗi.

4. Linux terminal thứ ba: bắt đầu sampler với cùng RunId; để chạy suốt benchmark:

   ```bash
   ./scripts/sample-resources.sh '<RUN_ID>'
   ```

   CSV được ghi vào `server/results/<RUN_ID>-server-resources.csv`.

5. Kiểm tra container/log, chờ gateway sẵn sàng rồi báo client bắt đầu:

   ```bash
   docker compose --env-file .env --profile bifrost --profile litellm -f compose.yaml -p ai-gateway-benchmark ps
   docker compose --env-file .env --profile bifrost --profile litellm -f compose.yaml -p ai-gateway-benchmark logs --tail 100
   ```

   URL client: `http://<VM_PRIVATE_IP>:8080/v1/chat/completions` cho Bifrost, `http://<VM_PRIVATE_IP>:4000/v1/chat/completions` cho LiteLLM.

## F. Đổi gateway và kết thúc

Chạy Bifrost và LiteLLM tuần tự, không đồng thời. Sau khi client báo run hoàn tất, dừng sampler/monitor cũ bằng Ctrl+C, giữ lại CSV, chọn gateway còn lại bằng selector, tạo RunId mới và khởi động lại Windows host monitor, guest guard, sampler. Giữ nguyên workload/profile giữa hai gateway.

Chuyển hai CSV server sang local qua kênh nội bộ được chấp thuận để validate cùng JSON/client CSV. Không gửi `.env` hoặc credentials. Giao nhận gateway, SHA repo/submodule, RunId, kết quả preflight, trạng thái guard, và đường dẫn artifacts. Không kết luận nếu validation thất bại.

## Xử lý sự cố

- Compose config thiếu env: tạo lại `.env` từ `.env.example`; không đưa secret vào Git.
- Build mocker lỗi: xác minh submodule đã init và guest truy cập được registry.
- Guard dừng gateway/VM: giữ artifacts, không tăng giới hạn; xử lý nguyên nhân RAM rồi chạy lại bằng RunId mới.
- Client không kết nối: kiểm tra route/IP, gateway, bind port và firewall source cụ thể; không mở port rộng hơn.
- Cài đặt cần reboot hoặc ảnh hưởng mạng/host: dừng và xin lịch từ người vận hành.
