# 使用官方 Python 镜像作为基础
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY requirements.txt .

# 为确保环境纯净，先强制卸载旧版本，再安装依赖
RUN pip uninstall -y python-telegram-bot || true
RUN pip install --no-cache-dir -r requirements.txt

# 在构建日志中打印已安装的版本以供验证
RUN echo "Verifying installed python-telegram-bot version:" && pip show python-telegram-bot

# 复制源代码
COPY src/ .

# 设置容器启动时执行的命令
CMD ["python", "main.py"] 