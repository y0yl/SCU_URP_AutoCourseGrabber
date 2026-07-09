# 四川大学SCU_URP自动化抢课

四川大学 SCU URP 教务选课系统自动化工具，包含命令行抢课脚本和本地可视化网页控制台。项目支持登录验证码 OCR、课程查询、余量轮询、两步提交、结果确认、运行日志和网页端任务管理。

本人已亲自验证该脚本按照推荐频率长时间执行不会被教务处标记，并能成功提交课程（2026.7月正选）。当脚本执行时已选人数减少或者已选人数不符合满课人数特征时，脚本将增加可能抢到该课程的附加日志并适当减小频率。

> Keywords: 四川大学, SCU, Sichuan University, URP, SCU URP, 四川大学URP, 抢课, 自动抢课, 选课, 选课系统, 课程抢课, course selection, course grabber, course enrollment automation, webui

## 功能概览

- **URP 登录**：`scu_login.py` 封装四川大学 URP 登录流程，使用 `ddddocr` 识别验证码，登录成功后复用 `requests.Session`。
- **课程查询**：`course_grabber.py list` 支持按课程号、课序号、课程名、教师、开课院系等条件查询课程。
- **自动抢课**：`course_grabber.py grab` 支持轮询课程余量，发现目标后自动提交选课。
- **直接提交**：`course_grabber.py submit` 可在查询到目标后直接执行提交流程。
- **多类别课程**：支持意向/预选课程、计划课程、校任选课程、院系课程、自由课程。
- **结果确认**：真实提交后可检查退课页和失败课程页，确认是否已经进入已选列表。
- **可视化网页**：`webui_server.py` 提供本地 WebUI，可保存配置、启动/停止任务、查看实时日志和历史记录。
- **日志统计**：网页端显示轮询、提交、成功、失败、502/503/504 等运行统计，并在抢课成功时弹窗提示。

## 项目结构

```text
.
├── course_grabber.py      # 课程查询、轮询和提交主脚本
├── scu_login.py           # 四川大学 URP 登录客户端
├── webui_server.py        # 本地 WebUI HTTP 服务
├── webui/
│   ├── index.html         # WebUI 主界面
│   ├── login.html         # WebUI 登录页
│   ├── config.json        # 本地配置文件，运行时生成/更新
│   └── runs.json          # 历史任务记录，运行时生成/更新
├── logs/                  # 运行日志目录，运行时生成
├── requirements.txt       # Python 依赖
├── WEBUI_README.md        # WebUI 使用说明
└── PROJECT_HANDOFF.md     # 项目交接与更多命令说明
```

## 环境要求

- Windows / macOS / Linux 均可运行，当前项目主要按 Windows PowerShell 使用方式编写示例。
- Python 3.10+，推荐 Python 3.12。
- 可访问四川大学 URP 教务系统网络环境。

安装依赖：

```powershell
pip install -r requirements.txt
```

依赖包括：

- `requests`：HTTP 会话与请求
- `Pillow`：验证码图片预处理
- `ddddocr`：验证码 OCR

## 快速开始：WebUI

启动本地网页控制台：

```powershell
cd C:\Users\yi\Documents\urpQ
python .\webui_server.py
```

浏览器打开：

```text
http://127.0.0.1:8765
```

如需局域网访问：

```powershell
python .\webui_server.py --host 0.0.0.0 --port 8765
```

网页中可填写 URP 账号、密码、课程类别、课程号/课序号、轮询间隔等参数，然后启动 `list` 查询或 `grab` 抢课任务。

## 快速开始：命令行

### 1. 设置账号密码

方式一：环境变量，推荐：

```powershell
$env:SCU_USERNAME="你的学号"
$env:SCU_PASSWORD="你的密码"
```

方式二：命令参数：

```powershell
python .\course_grabber.py --username 你的学号 --password 你的密码 list --category free
```

### 2. 查询课程

按课程号查询：

```powershell
python .\course_grabber.py list --category free --course-id 888006010A07
```

按课程号 + 课序号精确查询：

```powershell
python .\course_grabber.py list --category free --course-id 888006010A07_01
```

按课程名或教师模糊搜索：

```powershell
python .\course_grabber.py list --category free --search 网球
python .\course_grabber.py list --category free --name 网球 --teacher 张三
```

显示真实已选人数：

```powershell
python .\course_grabber.py list --category free --course-id 888006010A07_01 --view-xk-count
```

### 3. Dry-run 检查提交参数

正式提交前建议先用 `--dry-run` 检查匹配目标和 payload：

```powershell
python .\course_grabber.py grab --category free --course-id 888006010A07_01 --dry-run --once
```

### 4. 自动轮询抢课

```powershell
python .\course_grabber.py grab --category free --course-id 888006010A07_01 --interval 2.0 --jitter 1.3
```

多个目标用英文逗号分隔：

```powershell
python .\course_grabber.py grab --category free --course-id 888006010A07_01,888006010A07_14 --interval 2.0 --jitter 1.3
```

只填写课程号时，会尝试匹配该课程号下的可用课序：

```powershell
python .\course_grabber.py grab --category free --course-id 888006010A07 --interval 2.0 --jitter 1.3
```

## 课程类别参数

`--category` 支持：

| 参数 | 含义 |
| --- | --- |
| `intent` | 意向/预选课程 |
| `plan` | 计划课程 |
| `school` | 校任选课程 |
| `depart` | 院系课程 |
| `free` | 自由课程 |

## 常用参数

| 参数 | 说明 |
| --- | --- |
| `--course-id` | 目标课程，支持 `kch` 或 `kch_kxh`，多个用逗号分隔 |
| `--kch` | 课程号，多个用逗号分隔 |
| `--kxh` | 课序号，多个用逗号分隔 |
| `--name` | 课程名称，抢课匹配时要求与系统课程名严格相同 |
| `--teacher` | 教师姓名，可与 `--name` 配合使用 |
| `--search` | 按课程名/教师模糊搜索 |
| `--view-xk-count` | 调用“点击查看”接口读取真实已选人数 |
| `--dump-json` | 导出原始 courseList JSON，便于排查字段 |
| `--interval` | 基础轮询间隔秒，推荐 `2.0` |
| `--jitter` | 随机抖动秒，推荐 `1.3` |
| `--max-attempts` | 最大轮询次数，`0` 表示一直轮询 |
| `--once` | 只执行一轮 |
| `--no-poll` | 不轮询，查询到目标后提交一轮 |
| `--system-not-open` | 系统未开放/不稳定时使用已缓存目标继续提交，降低延迟 |
| `--dry-run` | 不真实提交，只打印提交参数 |
| `--no-confirm` | 提交后不检查已选/失败页面确认结果 |

## 抢课成功判断

程序真实提交后，会尝试确认最终状态：

- 日志中出现 `"final_status": "selected"` 表示课程已在已选列表中。
- 如果课程出现在失败课程页，会标记为失败状态。
- WebUI 会弹出抢课成功提示，并更新页面标题。

## 本地文件与隐私

运行过程中会生成：

- `webui/config.json`：WebUI 配置
- `webui/runs.json`：历史任务记录
- `logs/*.log`：标准输出日志
- `logs/*.err.log`：错误日志
- `captcha_debug/`：如启用验证码调试，会保存验证码图片

这些文件可能包含本地配置、账号或运行记录，不建议提交到 GitHub。

## 更多说明

- [`WEBUI_README.md`](WEBUI_README.md)：可视化网页使用说明
- [`PROJECT_HANDOFF.md`](PROJECT_HANDOFF.md)：完整项目交接、实现细节与更多命令
