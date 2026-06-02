FROM python:3.12-slim

WORKDIR /app

COPY controller/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn

COPY controller/ .

ENV MANET_WEB_DIR=/app/dist
ENV MANET_PORT=8000

EXPOSE 8000

CMD ["python", "main.py"]