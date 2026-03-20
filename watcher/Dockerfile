FROM python:3.11-slim

WORKDIR /app

# 安裝系統依賴
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

# 複製依賴檔案
COPY requirements.txt .

# 安裝 Python 依賴
RUN pip install --no-cache-dir -r requirements.txt

# 複製主程式
COPY bridge.py .

# 建立日誌目錄
RUN mkdir -p /var/log/bridge

# 執行 Watcher
CMD ["python", "-u", "bridge.py"]
