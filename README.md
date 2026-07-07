# 四川大学SCU_URP自动化抢课

四川大学 SCU URP 选课系统自动化抢课工具，包含命令行抢课脚本和本地可视化网页控制台。

> Keywords: 四川大学, SCU, Sichuan University, URP, SCU URP, 四川大学URP, 抢课, 自动抢课, 选课, 选课系统, 课程抢课, course selection, course grabber, course enrollment automation, webui

## 项目简介

本项目面向四川大学 URP 教务选课场景，提供：

- `scu_login.py`：四川大学 URP 登录客户端
- `course_grabber.py`：SCU URP 自动化查询课程、轮询余量、提交选课
- `webui_server.py`：本地可视化控制台，支持配置、启动/停止任务、查看实时日志
- `webui/`：浏览器网页界面

## 适合搜索的相关主题

- 四川大学抢课
- 四川大学选课
- 四川大学 URP
- SCU URP
- SCU course grabber
- SCU course selection automation
- URP 自动化抢课
- URP 选课脚本
- Python 抢课脚本

## 快速启动

```powershell
python .\webui_server.py
```

浏览器打开：<http://127.0.0.1:8765>

## 更多说明

- [`WEBUI_README.md`](WEBUI_README.md)：可视化网页使用说明
- [`PROJECT_HANDOFF.md`](PROJECT_HANDOFF.md)：完整项目交接与命令行用法
