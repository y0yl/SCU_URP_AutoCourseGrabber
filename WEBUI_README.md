# 四川大学SCU_URP自动化抢课：可视化网页

## 启动

```powershell
cd C:\Users\yi\Documents\urpQ
python .\webui_server.py
```

打开：

```text
http://127.0.0.1:8765
```

## 功能

- 在网页中修改并保存 `course_grabber.py` 的常用配置
- 启动/停止 `list` 查询或 `grab` 轮询抢课任务
- 实时查看标准输出日志
- 选择历史日志查看
- 显示轮询、提交、成功、失败、502/503/504 的简单统计

## 生成文件

- 配置：`C:\Users\yi\Documents\urpQ\webui\config.json`
- 日志：`C:\Users\yi\Documents\urpQ\logs\*.log`
- 历史任务：`C:\Users\yi\Documents\urpQ\webui\runs.json`

## 使用建议

1. 先在网页中填好账号和抢课条件。
   - 网页会将教务账号/密码通过子进程环境变量传给 `course_grabber.py`，不会把密码写入命令行。
   - 如果不想在网页中保存密码，也可以在启动前设置 `SCU_USERNAME` / `SCU_PASSWORD` 环境变量。
2. 建议使用完整 `course-id`。
   - 单个示例：`888006010A07_01`
   - 多个示例：`888006010A07_01,888006010A07_14`
3. 需要局域网访问时可以这样启动：

```powershell
python .\webui_server.py --host 0.0.0.0 --port 8765
```

请配合网页访问密码/本机防火墙规则使用。

## 抢课成功提示

- 日志出现 `"final_status": "selected"` 时，表示程序确认课程已在已选列表中。
- 网页会弹出已抢到课程的提示，并改变页面标题。
- 弹窗信息会暂存在 `localStorage`，刷新页面后仍可看到。

## 注意事项

- `scu_login.py` 依赖 `ddddocr` 识别验证码。
- 请不要把本地生成的 `webui/config.json`、`webui/runs.json` 和 `logs/*.log` 提交到 GitHub。
- 正式抢课前可先勾选 `dry-run` 检查查询条件和提交参数。
