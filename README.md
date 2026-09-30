# 数控刀补复核台

操作员提交刀具编号与刀补微米值；后台 worker 用 PostgreSQL 行锁（`select_for_update(skip_locked=True)`）认领待复核记录，按绝对值是否不超过 12 微米给出「合格」或「超差」。

## 落款台（认领人落款与在途改派）

- **三处同源**：认领写入、专页落款、改派后落款全部读写 `OffsetSubmission.claimant` 这一列，再无第二处存放落款名。
- 进程切入「复核中」时写入认领人（甲/乙/丙台），办结后原样保留；新单一进复核中即可看到认领人。
- 操作员可把「复核中、未结清」的单转交给另一认领名，写入**改派痕迹簿**（原认领人、新认领人、操作人、时间、备注，名称做字符串快照）；**已办结的不许改派**。
- 改派与办结都在同一行锁内先复核状态再落库：两者撞车时，办结先成则改派整体失败（409），不会留下半截换人或半截痕迹；改派先成则随后办结沿用新认领人落款。
- **复核员只读**：可看落款、按人筛已落款清单、看痕迹簿，但不能改派（接口返回 403）。
- 菜单「落款台」含三个页签：在途改派、已落款清单（按认领人筛 + 按刀号核对落款与认领进程一致）、改派痕迹簿（按人筛）。


## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | Django 5 + django-ninja（ASGI / uvicorn） |
| 前端 | SolidJS + Vite，nginx 反代 `/api` |
| 数据库 | PostgreSQL 16 |
| 鉴权 | JWT（python-jose），令牌存浏览器 localStorage |

## 端口

| 服务 | 地址 |
|------|------|
| 页面 | http://localhost:3196 |
| 接口 | http://localhost:8196 |
| PostgreSQL | localhost:54396（库名 `cncoffset`） |

## 账号

| 用户 | 密码 | 权限 |
|------|------|------|
| machinist | machine123456 | 可提交刀补 |
| auditor | audit123456 | 只读列表 |

## 启动

```bash
cd projects/17-cnc-tool-offset-desk
docker compose up --build
```

健康检查：`GET http://localhost:8196/api/health` → `{"status":"ok"}`

## 验收

1. machinist 登录后，种子数据应显示刀具 T01 合格（刀补 5 µm，落款甲台复核员）、T09 超差（刀补 20 µm，落款甲台复核员）。
2. 提交一条新刀补后，状态先为「待复核」；worker 认领后变「复核中」并立刻显示认领人（默认甲台复核员），在途窗口（`PROCESSING_HOLD_SECONDS`，默认 8 秒）后办结给出结论，落款保留。
3. 在「落款台 · 在途改派」把一条复核中的单改派给乙台：专页落款立即变乙台，痕迹簿新增一条；待其办结，落款仍是乙台。
4. 已办结的单不出现改派入口/接口返回 409；改派与办结撞车且办结先成时改派失败，落款与痕迹簿均无半截改动。
5. auditor 登录后只能看列表、落款与痕迹簿，没有提交表单与改派控件（强行调改派接口返回 403）。
6. 「已落款清单」可按认领人筛、按刀号核对落款与认领进程一致。

## worker 落款环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `CLAIMANT_NAME` / `CLAIMANT_CODE` | 甲台复核员 / A | worker 认领与落款所用认领名（不存在则自建） |
| `PROCESSING_HOLD_SECONDS` | 8 | 切入复核中后停留多久再办结，即「在途改派」窗口 |
| `MAX_IN_FLIGHT` | 8 | 同时在途（停留中）的上限 |

## 目录

```text
backend/          Django 工程（config/、desk/、worker.py）
frontend/         SolidJS 单页
docker-compose.yml
PRD.md
```
