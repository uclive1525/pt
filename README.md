# 种控台 · PT 站自动化平台

馒头等 PT 站的自托管自动化工具：自动签到保活、关键词监控下载、分享率辅助刷流，并支持多机 Transmission 与三色墨水屏面板。

[![Version](https://img.shields.io/badge/version-1.0.5-blue)](VERSION)
[![Docker](https://img.shields.io/badge/docker-amd64-2496ED?logo=docker&logoColor=white)](Dockerfile)
[![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](requirements.txt)

> 截图中的 UID、账号、API Key、站点地址等敏感信息均已打码，仅作功能展示。

---

## 能做什么

- **拟人防封调度**：随机间隔、小时配额、静默时段，降低机刷风险  
- **爱好监控**：关键词匹配，按清晰度 / 体积精选版本并自动下载  
- **分享监控**：按魔力公式优选大体积、少做种、存活久的种子  
- **签到保活**：每日自动浏览，维持账号活跃  
- **多机 Transmission**：多 RPC 配置、任务概览、暂停删除、自动清理  
- **三色墨水屏**：400×300 BMP，天气农历 + 站点 / TR / 监控数据一屏看完  
- **心愿单**：独立收集页，可对外分享链接  

---

## 界面预览

### 桌面端

| 登录页 | 首页概览 |
| :---: | :---: |
| ![登录页](docs/images/login.png) | ![首页概览](docs/images/dash.png) |

| Transmission | 站点配置 |
| :---: | :---: |
| ![Transmission](docs/images/transmission.png) | ![站点配置](docs/images/site.png) |

### 移动端

| 登录 | 首页 |
| :---: | :---: |
| ![移动端登录](docs/images/mobile-login.png) | ![移动端首页](docs/images/mobile-dash.png) |

| Transmission | 心愿单 |
| :---: | :---: |
| ![移动端 TR](docs/images/mobile-tr.png) | ![心愿单](docs/images/wish-demo.png) |

### 墨水屏（400×300）

设备请求 `GET /generate-image` 拉取 BMP，展示天气、农历、种控台与 TR 汇总。

| 面板预览 | 实机效果 |
| :---: | :---: |
| ![墨水屏面板](docs/images/ink-panel.png) | ![硬件效果](docs/images/ink-hardware.jpg) |

---

## 功能一览

| 模块 | 说明 |
| --- | --- |
| 拟人防封 | 随机间隔、小时配额、静默时段、页面/动作延迟 |
| 爱好监控 | 关键词匹配，按清晰度/体积精选最多 N 个版本 |
| 分享监控 | 按魔力公式推荐：大体积 · 少做种 · 存活久 |
| 签到保活 | 每日自动浏览，维持账号活跃 |
| Transmission | 多服务器、任务概览、暂停/删除、自动清理规则 |
| 日志中心 | 访问 / PT / 下载 / 墨水屏日志 |
| 墨水屏 | 400×300 三色 BMP，局域网直连刷新 |
| 心愿单 | 独立收集页，可对外分享链接 |

---

## 快速开始

### 环境要求

- Docker（推荐）或 Python 3.12+
- 可访问 PT 站点 API
- （可选）Transmission RPC
- （可选）COOIOT / 同类墨水屏设备

### Docker 部署

```bash
# 1. 打包（本地 amd64 镜像 + tar.gz）
./pack.sh

# 2. 导入镜像（群晖 / NAS 上）
docker load -i dist/mt-pt-1.0.5-amd64.tar.gz

# 3. 启动
mkdir -p data downloads
docker compose -f docker-compose.synology.yml up -d
```

浏览器访问 `http://<主机IP>:8080`，首次登录后修改系统密码。

> 群晖 Container Manager 换镜像后请检查端口映射：`8080 → 8080`。

### 本地开发

```bash
pip install -r requirements.txt
DATA_DIR=./data DOWNLOAD_DIR=./downloads uvicorn app.main:app --host 0.0.0.0 --port 8080
```

---

## 墨水屏配置

1. 在 **系统设置 → 墨水屏面板** 填写省市区（默认成都），用于天气与底栏地点。  
2. 设备图片 URL：

   ```
   http://<主机IP>:8080/generate-image
   ```

3. 响应头 `wt`：`1005`=5 分钟，`0`=1 小时，`1`=2 小时。  
4. 输出：400×300 BMP，黑 / 白 / 红；设备渲染建议选「不处理」。

---

## 目录结构

```
app/          FastAPI 后端（调度、站点、TR、墨水屏）
static/       Web 管理界面
data/         配置与运行数据（挂载卷，勿提交）
downloads/    种子下载目录（挂载卷，勿提交）
dist/         打包产物 mt-pt-<version>-amd64.tar.gz
docs/images/  文档截图（已打码）
```

---

## 版本

当前版本见 [VERSION](VERSION)，接口 `GET /api/version` 可查询。

---

## 支持

感兴趣可以支持下硬件：

![支持](docs/images/support-qr.jpg)

---

## 免责声明

本项目仅供学习与个人站点管理使用。请遵守所在 PT 站点规则与当地法律法规，合理使用自动化功能，风险自负。
