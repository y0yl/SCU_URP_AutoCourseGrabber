# 四川大学SCU_URP自动化抢课：可视化网页

本项目自带本地 WebUI，用于在浏览器中配置并运行 `course_grabber.py`，适合不想每次手写命令行参数的场景。

## 启动

```powershell
cd C:\Users\yi\Documents\urpQ
python .\webui_server.py
```

打开：

```text
http://127.0.0.1:8765
```

局域网访问：

```powershell
python .\webui_server.py --host 0.0.0.0 --port 8765
```

## 主要功能

- 在网页中填写并保存常用抢课配置。
- 支持 `list` 查询和 `grab` 轮询抢课任务。
- 支持课程类别、课程号、课序号、课程名、教师、轮询间隔、随机抖动等参数。
- 可启动/停止当前任务。
- 实时查看标准输出日志和错误日志。
- 查看历史运行记录。
- 统计轮询、提交、成功、失败、502/503/504 等次数。
- 抢课成功时弹窗提示，并改变页面标题。
- 可选 WebUI 访问密码。

## 生成文件

- 配置文件：`C:\Users\yi\Documents\urpQ\webui\config.json`
- 历史任务：`C:\Users\yi\Documents\urpQ\webui\runs.json`
- 运行日志：`C:\Users\yi\Documents\urpQ\logs\*.log`
- 错误日志：`C:\Users\yi\Documents\urpQ\logs\*.err.log`

## 使用建议

1. 先填写 URP 账号、密码和抢课条件。
2. 目标课程建议优先使用完整 `course-id`：
   - 单个目标：`888006010A07_01`
   - 多个目标：`888006010A07_01,888006010A07_14`
3. 正式抢课前可先勾选或传入 `dry-run`，检查查询条件和提交参数。
4. 如果不想在网页配置中保存 URP 密码，可在启动前设置环境变量：

```powershell
$env:SCU_USERNAME="你的学号"
$env:SCU_PASSWORD="你的密码"
python .\webui_server.py
```

WebUI 启动子进程时会通过环境变量把账号密码传给 `course_grabber.py`，不会把密码写入命令行参数。

## 成功提示

- 日志出现 `"final_status": "selected"` 表示程序确认课程已在已选列表中。
- 页面会弹出“已抢到课程”的提示。
- 提示信息会暂存在浏览器 `localStorage`，刷新页面后仍可看到。

## 注意

- `scu_login.py` 依赖 `ddddocr` 识别验证码。
- `webui/config.json`、`webui/runs.json`、`logs/*.log`、验证码调试图片等本地运行文件不建议提交到 GitHub。
- 如开启局域网访问，建议设置 WebUI 访问密码。
