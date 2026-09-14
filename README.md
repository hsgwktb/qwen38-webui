# qwen38-webui

Qwen3.8-27B Uncensored（llama.cpp / GGUF）的对话网页 + OpenAI 兼容网关。
由 ModelScope/Colab 笔记本 `Qwen3.8-27B-Uncensored-ModelScope.ipynb` 第 6 格下载运行，
取代原先内嵌在 notebook 里的 base64 版本。

## 文件

- `webui.py` — FastAPI 服务：`/` 返回聊天页，其余路径反向代理到 `127.0.0.1:8081` 的 llama-server；
  上游不可用时返回 502 并说明原因（旧版这里是未捕获异常，表现为前端只看到 HTTP 500）。
- `index.html` — 聊天界面（含思考折叠、API 信息面板、连接自检）。

## 部署时的占位符

`webui.py` 里有两个占位符，由 notebook 在运行时替换：

- `__DEPLOY_KEY__` — llama-server 的 API Key
- `__ALIAS__` — 对外显示的模型名

## 本地运行

```bash
python webui.py     # 监听 127.0.0.1:8000，需 index.html 同目录
```
