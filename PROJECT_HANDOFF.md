# SCU URP 抢课项目交接说明

本项目目录：`C:\Users\yi\Documents\urpQ`

## 新会话快速启动提示

在新会话中可以直接这样说：

> 读取 `C:\Users\yi\Documents\urpQ\PROJECT_HANDOFF.md`，根据里面的说明使用 `course_grabber.py`。我要抢课：课程名/课程号/课序号是 `xxx`，请先查完整 course-id，再后台轮询抢课，加随机抖动，并把日志路径告诉我。

如果只给类似：

```text
体育-3网球(888006010A07_01)、体育-3网球(888006010A07_14)
```

后续助手应执行：

1. 进入项目目录：`C:\Users\yi\Documents\urpQ`
2. 用 `course_grabber.py list` 在 `free/plan/school/depart/intent` 中定位完整 `course-id`
3. 用完整 `course-id` 运行 `grab`
4. 建议后台运行，日志写入文件
5. 定期查看日志，确认是否出现 `提交目标` / `提交成功`

---

## 当前重要文件

```text
C:\Users\yi\Documents\urpQ\scu_login.py
C:\Users\yi\Documents\urpQ\course_grabber.py
C:\Users\yi\Documents\urpQ\requirements.txt
C:\Users\yi\Documents\urpQ\PROJECT_HANDOFF.md
```

## 环境依赖

```powershell
cd C:\Users\yi\Documents\urpQ
pip install -r requirements.txt
```

`requirements.txt`：

```text
requests>=2.31.0
Pillow>=10.0.0
ddddocr>=1.5.6
```

---

## 登录模块：scu_login.py

已实现四川大学教务系统登录客户端：

- 登录地址：`http://zhjw.scu.edu.cn/login`
- 登录后跳转：`http://zhjw.scu.edu.cn/index`
- 登录方式：`requests.Session` 保持会话
- 验证码：本地 `ddddocr`
- ??????????????????????? `SCU_USERNAME` / `SCU_PASSWORD`????? `--username` / `--password` ??

登录测试：

```powershell
cd C:\Users\yi\Documents\urpQ
python .\scu_login.py
```

可选验证码调试：

```powershell
python .\scu_login.py --debug-captcha-dir .\captcha_debug
```

Python 调用入口：

```python
from scu_login import create_logged_in_client
client = create_logged_in_client(verbose=False)
resp = client.get('/index')
```

---

## 抢课模块：course_grabber.py

文件：

```text
C:\Users\yi\Documents\urpQ\course_grabber.py
```

已实现：

1. 自动登录并进入选课首页：
   - `/student/courseSelect/courseSelect/index#iframe-xk`
2. 自动提取：
   - `tokenValue`
   - `fajhh`
   - 推荐/方案/系任/校任/自由选课入口
3. 支持选课类别：
   - `intent`：推荐/计划选课
   - `plan`：方案选课
   - `school`：校任选课
   - `depart`：系任选课
   - `free`：自由选课
4. 查询课程列表接口并解析余量：
   - `bkskyl`
5. 支持按以下条件筛选：
   - `--course-id`
   - `--kch` 课程号
   - `--kxh` 课序号/教学班号
   - `--name` 课程名
   - `--teacher` 教师
6. 支持多目标：
   - `--course-id id1,id2,id3`
   - `--kxh 01,14`
7. 支持轮询、间隔、随机抖动：
   - `--interval`
   - `--jitter`
8. 支持后台运行和日志文件。
9. 已补全真实提交链路：
   - 先 POST `/student/courseSelect/selectCourse/checkInputCodeAndSubmit`
   - 返回 `result: ok` 后继续 POST `/student/courseSelect/selectCourses/waitingfor`

---

## 已验证真实提交成功

为了验证脚本，已实际提交过一门可选课：

```text
基础力学实验
course-id: 305135010_01_2026-2027-1-1
```

提交返回：

```json
{
  "result": "ok",
  "waitingfor_status": 200,
  "waitingfor_url": "http://zhjw.scu.edu.cn/student/courseSelect/selectCourses/waitingfor"
}
```

随后查询退课页面，已确认出现：

```text
305135010
基础力学实验
```

说明真实选课链路已验证成功。

注意：用户说后续会自己退掉这门验证课。

另一次测试：

```text
科学进步与技术革命
999011020_09_2026-2027-1-1
```

前置与 waitingfor 链路也成功，但最终失败，失败信息显示课程时间冲突。

---

## 常用命令

### 1. 查看帮助

```powershell
cd C:\Users\yi\Documents\urpQ
python .\course_grabber.py --help
python .\course_grabber.py list --help
python .\course_grabber.py grab --help
```

### 2. 按课程名查询

```powershell
python .\course_grabber.py --quiet-login list --category free --name 课程名 --limit 20
```

### 3. 按课程号和课序号查询

```powershell
python .\course_grabber.py --quiet-login list --category free --kch 888006010A07 --kxh 01 --limit 10
```

### 4. 多课序查询

```powershell
python .\course_grabber.py --quiet-login list --category free --kch 888006010A07 --kxh 01,14 --limit 10
```

### 5. 用完整 course-id 查询

```powershell
python .\course_grabber.py --quiet-login list --category free --course-id 888006010A07_01_2026-2027-1-1,888006010A07_14_2026-2027-1-1 --kch 888006010A07 --limit 10
```

### 6. dry-run 演练，不真实提交

```powershell
python .\course_grabber.py --quiet-login grab --category free --course-id 888006010A07_01_2026-2027-1-1 --name 体育-3网球 --once --dry-run
```

### 7. 前台轮询抢课

```powershell
python .\course_grabber.py --quiet-login grab --category free --course-id 888006010A07_01_2026-2027-1-1,888006010A07_14_2026-2027-1-1 --kch 888006010A07 --name 体育-3网球 --interval 1.35 --jitter 0.9
```

### 8. 限定轮数

```powershell
python .\course_grabber.py --quiet-login grab --category free --course-id 888006010A07_01_2026-2027-1-1,888006010A07_14_2026-2027-1-1 --kch 888006010A07 --name 体育-3网球 --interval 1.35 --jitter 0.9 --max-attempts 600
```

---

## 后台轮询模板

推荐新会话中用这个方式跑，避免工具超时导致中断。

```powershell
cd C:\Users\yi\Documents\urpQ

$log = Join-Path (Get-Location) 'grab_course.log'
$err = Join-Path (Get-Location) 'grab_course.err.log'

# 可选：清理旧的同类进程
Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
  Where-Object { $_.CommandLine -match 'course_grabber\.py' -and $_.CommandLine -match '课程号或关键字' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$args = @(
  '.\course_grabber.py', '--quiet-login', 'grab',
  '--category', 'free',
  '--course-id', '完整course-id1,完整course-id2',
  '--kch', '课程号',
  '--name', '课程名',
  '--interval', '1.35',
  '--jitter', '0.9',
  '--max-attempts', '600'
)

$p = Start-Process -FilePath 'python' `
  -ArgumentList $args `
  -WorkingDirectory (Get-Location) `
  -RedirectStandardOutput $log `
  -RedirectStandardError $err `
  -WindowStyle Hidden `
  -PassThru

"started pid=$($p.Id)"
"stdout=$log"
"stderr=$err"
```

查看日志：

```powershell
Get-Content C:\Users\yi\Documents\urpQ\grab_course.log -Wait -Tail 30
```

停止后台抢课：

```powershell
Stop-Process -Id <PID> -Force
```

检查是否还在跑：

```powershell
Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
  Where-Object { $_.CommandLine -match 'course_grabber\.py' } |
  Select-Object ProcessId,CommandLine | Format-List
```

---

## 当前体育网球目标记录

用户之前指定：

```text
体育-3网球(888006010A07_01)
体育-3网球(888006010A07_14)
```

已定位完整 ID：

```text
888006010A07_01_2026-2027-1-1  体育-3网球  蔡舸
888006010A07_14_2026-2027-1-1  体育-3网球  任常胜
```

之前多次查询结果均为：

```text
余量=0
```

推荐抢课命令：

```powershell
cd C:\Users\yi\Documents\urpQ
python .\course_grabber.py --quiet-login grab --category free --course-id 888006010A07_01_2026-2027-1-1,888006010A07_14_2026-2027-1-1 --kch 888006010A07 --name 体育-3网球 --interval 1.35 --jitter 0.9
```

后台版本把上面参数填入“后台轮询模板”。

---

## 判断是否提交成功

日志中出现类似：

```text
提交目标：...
{
  "result": "ok",
  "waitingfor_status": 200,
  ...
}
提交成功
```

然后可查退课页面确认：

```powershell
python - <<'PY'
from pathlib import Path
from scu_login import create_logged_in_client
client = create_logged_in_client(verbose=False, max_attempts=8)
r = client.get('/student/courseSelect/quitCourse/index')
Path('quit_check.html').write_text(r.text, encoding=r.encoding or 'utf-8', errors='ignore')
print('status', r.status_code, 'len', len(r.text))
print('contains course id:', '课程号' in r.text)
PY
```

也可以直接搜索：

```powershell
Select-String -Path .\quit_check.html -Pattern '课程号|课程名|退课' | Select-Object -First 80
```

失败信息页面：

```powershell
python - <<'PY'
from pathlib import Path
from scu_login import create_logged_in_client
client = create_logged_in_client(verbose=False, max_attempts=8)
r = client.get('/student/courseSelect/courseSelectFailed/index')
Path('failed_check.html').write_text(r.text, encoding=r.encoding or 'utf-8', errors='ignore')
print('status', r.status_code, 'len', len(r.text))
PY
```

```powershell
Select-String -Path .\failed_check.html -Pattern '课程号|课程名|未成功原因|失败' | Select-Object -First 120
```

---

## 注意事项

1. 教务系统偶尔会返回 `502 Bad Gateway`，登录和查课都可能遇到。遇到 502 时可稍等后重试。
2. 真实提交必须执行两步：
   - `checkInputCodeAndSubmit`
   - `selectCourses/waitingfor`
3. `course_grabber.py` 已实现两步。
4. 如果只返回 `result=ok` 但没有进入 `waitingfor`，不能算最终选上。
5. 最终确认以退课页面出现该课，或失败信息页面没有该课为准。
6. 多目标抢课建议用完整 `course-id`，不要只用 `--kxh 01,14`，因为部分接口在不传单个课序时可能漏返回。
7. 如需抢多个课序，推荐：

```powershell
--course-id id1,id2,id3 --kch 课程号 --name 课程名
```

---

## 2026-07-07 代码整理更新

`course_grabber.py` 已整理为更稳的版本，重点变更：

1. 修复并明确真实提交链路：
   - 第一步：`/student/courseSelect/selectCourse/checkInputCodeAndSubmit`
   - 第二步：`/student/courseSelect/selectCourses/waitingfor`
2. 新增最终确认逻辑：
   - 默认提交后自动查 `/student/courseSelect/quitCourse/index`
   - 如果目标课程出现在退课页，`final_status = selected`
   - 同时查 `/student/courseSelect/courseSelectFailed/index`
   - 如果目标课程出现在失败页，`final_status = failed`，并返回失败片段
   - 未确认到则 `final_status = unknown`
3. `grab` 现在只有在 `final_status=selected` 时明确打印“提交成功”。
4. 新增 502/503/504 和网络错误重试：
   - 登录参数：`--login-retries`
   - 请求内部也会做临时错误重试
5. 新增确认相关参数：
   - `--no-confirm`：提交后不查退课/失败页
   - `--confirm-attempts N`：提交后确认次数，默认 4
6. `submit` 现在只接受单个 `--course-id`；多个目标请用 `grab`。

推荐继续使用：

```powershell
python .\course_grabber.py --quiet-login grab --category free --course-id 888006010A07_01_2026-2027-1-1,888006010A07_14_2026-2027-1-1 --kch 888006010A07 --name 体育-3网球 --interval 1.35 --jitter 0.9 --max-attempts 600 --confirm-attempts 4
```

如果日志中出现：

```json
"final_status": "selected",
"confirmed_selected": true
```

才表示最终确认选上。

如果出现：

```json
"final_status": "failed"
```

说明提交链路通了，但学校系统最终判定未成功，需看 `confirm_message` 中的失败原因。
