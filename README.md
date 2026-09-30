# 数控刀补复核台

操作员提交刀具编号与刀补微米值；后台 worker 用 PostgreSQL 行锁（`select_for_update(skip_locked=True)`）认领待复核记录，切入「复核中」时即以认领进程名（`WORKER_NAME`）写落款，按绝对值是否不超过 12 微米给出「合格」或「超差」，办结后落款原样保留。

「落款台」提供：在途改派、按人筛已落款清单、按刀号核对落款与认领进程是否一致、改派痕迹簿（只读）。

## 落款与改派规则

- **三处同源**：列表 / 详情 / 落款台展示的落款都读 `claimant_name` 同一列，由认领进程切入复核中时写入；改派只改这一处。
- **在途改派**：仅「复核中」的单可由操作员改派给另一认领名；已办结的单拒绝改派。
- **原子不撞车**：办结与改派都对同一行 `select_for_update`，并以 `status` 做守卫。办结先成则并发改派返回 409 且整体回滚，不会留下「换了名字没办结」或半截痕迹；痕迹簿与认领人更新在同一事务提交。
- **角色边界**：复核员只能阅读落款与痕迹簿，改派接口返回 403。
- 在途窗口由 `WORKER_PROCESSING_HOLD_SECONDS`（默认 2 秒，compose 设 6 秒）控制。

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
| machinist | machine123456 | 可提交刀补、在途改派 |
| auditor | audit123456 | 只读：看落款与痕迹簿，不可改派 |
| worker-01 / worker-02 | （不可登录，认领进程身份） | worker 落款名，可作改派目标 |

## 启动

```bash
cd projects/17-cnc-tool-offset-desk
docker compose up --build
```

健康检查：`GET http://localhost:8196/api/health` → `{"status":"ok"}`

## 验收

1. machinist 登录后，种子数据 T01 合格（5 µm）、T09 超差（20 µm），且已落款。
2. 提交新刀补：先「待复核」；worker 切入「复核中」即可在落款台看到认领人落款；办结后落款保留。
3. 在途时把单改派给另一认领名：落款立即换人，痕迹簿新增一条；办结后落款为改派后的名字。
4. 已办结的单不出现在在途改派，且对其改派返回 409，不留半截痕迹。
5. 「按刀号核对」可比对当前落款与认领进程首次落款及改派链是否一致。
6. auditor 登录只能读列表、落款与痕迹簿，无改派按钮，直接调接口返回 403。

## 目录

```text
backend/          Django 工程（config/、desk/、worker.py）
frontend/         SolidJS 单页
docker-compose.yml
PRD.md
```
