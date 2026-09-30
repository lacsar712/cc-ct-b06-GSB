import { createSignal, onMount, onCleanup, Show, For, createEffect } from "solid-js";
import {
  clearSession,
  createSubmission,
  fetchClaimants,
  fetchReassignLogs,
  fetchSubmission,
  fetchSubmissions,
  getUser,
  login,
  reassignSubmission,
  setSession,
} from "./api";

const statusLabel = {
  pending: "待复核",
  processing: "复核中",
  done: "已完成",
};

const roleLabel = {
  machinist: "操作员",
  auditor: "复核员",
};

function readHash() {
  const raw = (location.hash || "#/").replace(/^#/, "") || "/";
  let m = raw.match(/^\/detail\/(\d+)/);
  if (m) return { name: "detail", id: Number(m[1]) };
  if (raw.startsWith("/signature")) return { name: "signature", id: null };
  return { name: "home", id: null };
}

function fmt(ts) {
  return ts ? new Date(ts).toLocaleString() : "—";
}

function App() {
  const [user, setUser] = createSignal(getUser());
  const [route, setRoute] = createSignal(readHash());
  const [error, setError] = createSignal("");

  const [loginUser, setLoginUser] = createSignal("machinist");
  const [loginPass, setLoginPass] = createSignal("machine123456");

  function go(path) {
    location.hash = path;
  }

  onMount(() => {
    const onHash = () => setRoute(readHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  });

  async function handleLogin(e) {
    e.preventDefault();
    setError("");
    try {
      const data = await login(loginUser(), loginPass());
      setSession(data.token, {
        username: data.username,
        role: data.role,
        can_write: data.can_write,
      });
      setUser(getUser());
      go("#/");
    } catch (err) {
      setError(err.message);
    }
  }

  function handleLogout() {
    clearSession();
    setUser(null);
    go("#/");
  }

  return (
    <div class="page">
      <header class="topbar">
        <div class="brand">
          <h1>数控刀补复核台</h1>
          <p class="hint">
            认领进程切入复核中即写落款并保留到办结；落款台可在途改派、按人筛已落款、按刀号核对、查阅痕迹簿。
          </p>
        </div>
        <Show when={user()}>
          <nav class="topnav">
            <a
              href="#/"
              class={route().name === "home" ? "active" : ""}
              onClick={(e) => {
                e.preventDefault();
                go("#/");
              }}
            >
              复核总览
            </a>
            <a
              href="#/signature"
              class={route().name === "signature" ? "active" : ""}
              onClick={(e) => {
                e.preventDefault();
                go("#/signature");
              }}
            >
              落款台
            </a>
          </nav>
        </Show>
      </header>

      <Show when={error()}>
        <div class="banner error">{error()}</div>
      </Show>

      <Show
        when={user()}
        fallback={
          <section class="card">
            <h2>登录</h2>
            <form onSubmit={handleLogin} class="form">
              <label>
                用户名
                <input
                  value={loginUser()}
                  onInput={(e) => setLoginUser(e.currentTarget.value)}
                />
              </label>
              <label>
                密码
                <input
                  type="password"
                  value={loginPass()}
                  onInput={(e) => setLoginPass(e.currentTarget.value)}
                />
              </label>
              <button type="submit">进入系统</button>
            </form>
            <p class="hint">操作员 machinist / machine123456；复核员 auditor / audit123456（只读）</p>
          </section>
        }
      >
        <section class="card toolbar">
          <div>
            当前用户：<strong>{user().username}</strong>（{roleLabel[user().role] || user().role}
            {user().can_write ? "，可改派" : "，只读·不可改派"}）
          </div>
          <button type="button" class="ghost" onClick={handleLogout}>
            退出
          </button>
        </section>

        <Show when={route().name === "home"}>
          <OverviewPage user={user()} go={go} />
        </Show>
        <Show when={route().name === "signature"}>
          <SignaturePage user={user()} go={go} setError={setError} />
        </Show>
        <Show when={route().name === "detail"}>
          <DetailPage id={route().id} go={go} />
        </Show>
      </Show>
    </div>
  );
}

function OverviewPage(props) {
  const [rows, setRows] = createSignal([]);
  const [loading, setLoading] = createSignal(false);
  const [error, setError] = createSignal("");
  const [toolCode, setToolCode] = createSignal("");
  const [offsetUm, setOffsetUm] = createSignal("");

  async function loadRows() {
    setLoading(true);
    setError("");
    try {
      setRows(await fetchSubmissions());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  onMount(loadRows);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    try {
      await createSubmission(toolCode(), offsetUm());
      setToolCode("");
      setOffsetUm("");
      await loadRows();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <>
      <Show when={error()}>
        <div class="banner error">{error()}</div>
      </Show>
      <Show when={props.user.can_write}>
        <section class="card">
          <h2>提交刀补</h2>
          <form onSubmit={handleSubmit} class="form inline">
            <label>
              刀具编号
              <input
                placeholder="如 T01"
                value={toolCode()}
                onInput={(e) => setToolCode(e.currentTarget.value)}
                required
              />
            </label>
            <label>
              刀补（微米）
              <input
                type="number"
                value={offsetUm()}
                onInput={(e) => setOffsetUm(e.currentTarget.value)}
                required
              />
            </label>
            <button type="submit">提交待复核</button>
          </form>
        </section>
      </Show>

      <section class="card">
        <div class="toolbar">
          <h2>复核列表</h2>
          <button type="button" class="ghost" onClick={loadRows} disabled={loading()}>
            {loading() ? "刷新中…" : "刷新"}
          </button>
        </div>
        <table>
          <thead>
            <tr>
              <th>刀具</th>
              <th>刀补 µm</th>
              <th>状态</th>
              <th>结论</th>
              <th>落款（认领人）</th>
              <th>提交时间</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <For each={rows()}>
              {(row) => (
                <tr>
                  <td>{row.tool_code}</td>
                  <td>{row.offset_um}</td>
                  <td>{statusLabel[row.status] || row.status}</td>
                  <td class={row.verdict === "合格" ? "pass" : row.verdict === "超差" ? "fail" : ""}>
                    {row.verdict || "—"}
                  </td>
                  <td class={row.claimant_name ? "signer" : "muted"}>
                    {row.claimant_name || "—"}
                  </td>
                  <td>{fmt(row.created_at)}</td>
                  <td>
                    <button type="button" class="ghost" onClick={() => props.go(`#/detail/${row.id}`)}>
                      详情
                    </button>
                  </td>
                </tr>
              )}
            </For>
          </tbody>
        </table>
        <Show when={!rows().length && !loading()}>
          <p class="hint">暂无记录</p>
        </Show>
      </section>
    </>
  );
}

function DetailPage(props) {
  const [detail, setDetail] = createSignal(null);
  const [loading, setLoading] = createSignal(false);
  const [error, setError] = createSignal("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      setDetail(await fetchSubmission(props.id));
    } catch (e) {
      setError(e.message);
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }

  onMount(load);

  return (
    <section class="card">
      <div class="toolbar">
        <h2>刀补详情</h2>
        <button type="button" class="ghost" onClick={() => props.go("#/")}>
          返回总览
        </button>
      </div>
      <Show when={error()}>
        <div class="banner error">{error()}</div>
      </Show>
      <Show when={detail()} fallback={<p class="hint">{loading() ? "加载中…" : "未找到记录"}</p>}>
        {(d) => (
          <div class="detail-grid">
            <p>编号：{d().id}</p>
            <p>刀具：{d().tool_code}</p>
            <p>刀补 µm：{d().offset_um}</p>
            <p>状态：{statusLabel[d().status] || d().status}</p>
            <p class={d().verdict === "合格" ? "pass" : d().verdict === "超差" ? "fail" : ""}>
              结论：{d().verdict || "—"}
            </p>
            <p class={d().claimant_name ? "signer" : "muted"}>
              落款（认领人）：{d().claimant_name || "—"}
            </p>
            <p>认领时间：{fmt(d().claimed_at)}</p>
            <p>提交时间：{fmt(d().created_at)}</p>
            <p>复核时间：{fmt(d().reviewed_at)}</p>
            <Show when={d().status === "processing"}>
              <p class="hint">该单在途（复核中），可到落款台改派给另一认领名。</p>
              <div>
                <button type="button" class="ghost" onClick={() => props.go("#/signature")}>
                  前往落款台改派
                </button>
              </div>
            </Show>
          </div>
        )}
      </Show>
    </section>
  );
}

function SignaturePage(props) {
  const [inflight, setInflight] = createSignal([]);
  const [signed, setSigned] = createSignal([]);
  const [logs, setLogs] = createSignal([]);
  const [claimants, setClaimants] = createSignal([]);
  const [loading, setLoading] = createSignal(false);
  const [info, setInfo] = createSignal("");

  const [person, setPerson] = createSignal("");
  const [targets, setTargets] = createSignal({}); // submissionId -> selected username
  const [checkTool, setCheckTool] = createSignal("");
  const [checkResult, setCheckResult] = createSignal(null);
  const [busy, setBusy] = createSignal(0);

  async function loadAll() {
    setLoading(true);
    try {
      const needPeople = claimants().length === 0;
      const [inflightRows, signedRows, logRows, people] = await Promise.all([
        fetchSubmissions({ status: "processing" }),
        fetchSubmissions({ signed: true }),
        fetchReassignLogs(),
        needPeople ? fetchClaimants() : Promise.resolve(claimants()),
      ]);
      setInflight(inflightRows);
      setSigned(signedRows);
      setLogs(logRows);
      if (needPeople) setClaimants(people);
    } catch (e) {
      props.setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  onMount(() => {
    loadAll();
    // 在途单可能随时被办结，轮询刷新，避免改派落到已办结单上。
    const timer = setInterval(loadAll, 2500);
    onCleanup(() => clearInterval(timer));
  });

  const filteredSigned = () =>
    person() ? signed().filter((r) => r.claimant_name === person()) : signed();

  function targetFor(row) {
    return targets()[row.id] ?? "";
  }

  function setTarget(id, username) {
    setTargets((m) => ({ ...m, [id]: username }));
  }

  async function handleReassign(row) {
    const uname = targetFor(row);
    if (!uname) {
      props.setError("请先选择新的认领人");
      return;
    }
    props.setError("");
    setInfo("");
    setBusy((n) => n + 1);
    try {
      const updated = await reassignSubmission(row.id, uname);
      setInfo(`已改派：${row.tool_code} 落款改为「${updated.claimant_name}」`);
      await loadAll();
    } catch (e) {
      // 撞车：办结先成 → 409；刷新让在途列表移除该单
      props.setError(`${row.tool_code} 改派失败：${e.message}（已刷新）`);
      await loadAll();
    } finally {
      setBusy((n) => n - 1);
    }
  }

  async function handleCheck(e) {
    e.preventDefault();
    props.setError("");
    const code = checkTool().trim();
    if (!code) return;
    try {
      const [rows, toolLogs] = await Promise.all([
        fetchSubmissions({ tool_code: code }),
        fetchReassignLogs({ tool_code: code }),
      ]);
      setCheckResult({ code, rows, logs: toolLogs });
    } catch (err) {
      props.setError(err.message);
    }
  }

  return (
    <>
      <Show when={info()}>
        <div class="banner ok">{info()}</div>
      </Show>

      {/* 在途改派 */}
      <section class="card">
        <div class="toolbar">
          <h2>在途改派（复核中）</h2>
          <button type="button" class="ghost" onClick={loadAll} disabled={loading()}>
            {loading() ? "刷新中…" : "刷新"}
          </button>
        </div>
        <Show when={!props.user.can_write}>
          <p class="hint">复核侧只读：可查看在途单与落款，但不能改派。</p>
        </Show>
        <table>
          <thead>
            <tr>
              <th>刀具</th>
              <th>刀补 µm</th>
              <th>当前落款</th>
              <th>认领时间</th>
              <Show when={props.user.can_write}>
                <th>改派给</th>
                <th></th>
              </Show>
            </tr>
          </thead>
          <tbody>
            <For each={inflight()}>
              {(row) => (
                <tr>
                  <td>{row.tool_code}</td>
                  <td>{row.offset_um}</td>
                  <td class="signer">{row.claimant_name || "—"}</td>
                  <td>{fmt(row.claimed_at)}</td>
                  <Show when={props.user.can_write}>
                    <td>
                      <select value={targetFor(row)} onChange={(e) => setTarget(row.id, e.currentTarget.value)}>
                        <option value="">选择认领人…</option>
                        <For each={claimants()}>
                          {(c) => (
                            <option value={c.username} disabled={c.display_name === row.claimant_name}>
                              {c.display_name}
                            </option>
                          )}
                        </For>
                      </select>
                    </td>
                    <td>
                      <button
                        type="button"
                        onClick={() => handleReassign(row)}
                        disabled={busy() > 0 || !targetFor(row)}
                      >
                        改派
                      </button>
                    </td>
                  </Show>
                </tr>
              )}
            </For>
          </tbody>
        </table>
        <Show when={!inflight().length}>
          <p class="hint">当前没有复核中（在途）的单。</p>
        </Show>
      </section>

      {/* 按人筛已落款清单 */}
      <section class="card">
        <div class="toolbar">
          <h2>已落款清单</h2>
          <label class="inline-filter">
            按认领人筛：
            <select value={person()} onChange={(e) => setPerson(e.currentTarget.value)}>
              <option value="">全部</option>
              <For each={claimants()}>
                {(c) => <option value={c.display_name}>{c.display_name}</option>}
              </For>
            </select>
          </label>
        </div>
        <table>
          <thead>
            <tr>
              <th>刀具</th>
              <th>状态</th>
              <th>结论</th>
              <th>落款（认领人）</th>
              <th>认领时间</th>
              <th>复核时间</th>
            </tr>
          </thead>
          <tbody>
            <For each={filteredSigned()}>
              {(row) => (
                <tr>
                  <td>{row.tool_code}</td>
                  <td>{statusLabel[row.status] || row.status}</td>
                  <td class={row.verdict === "合格" ? "pass" : row.verdict === "超差" ? "fail" : ""}>
                    {row.verdict || "—"}
                  </td>
                  <td class="signer">{row.claimant_name}</td>
                  <td>{fmt(row.claimed_at)}</td>
                  <td>{fmt(row.reviewed_at)}</td>
                </tr>
              )}
            </For>
          </tbody>
        </table>
        <Show when={!filteredSigned().length}>
          <p class="hint">无已落款记录。</p>
        </Show>
      </section>

      {/* 按刀号核对落款 */}
      <section class="card">
        <h2>按刀号核对落款</h2>
        <form onSubmit={handleCheck} class="form inline">
          <label>
            刀具编号
            <input
              placeholder="如 T01"
              value={checkTool()}
              onInput={(e) => setCheckTool(e.currentTarget.value)}
              required
            />
          </label>
          <button type="submit">核对</button>
        </form>
        <Show when={checkResult()}>
          {(r) => (
            <div class="check-box">
              <Show when={!r().rows.length}>
                <p class="hint">未找到刀号「{r().code}」。</p>
              </Show>
              <For each={r().rows}>
                {(row) => {
                  // 痕迹簿按时间倒序返回，这里正序排成本单的改派链。
                  const chain = r()
                    .logs.filter((l) => l.submission_id === row.id)
                    .slice()
                    .sort((a, b) => a.id - b.id);
                  const origin = chain.length ? chain[0].from_claimant_name : row.claimant_name;
                  const tail = chain.length ? chain[chain.length - 1].to_claimant_name : row.claimant_name;
                  const consistent = tail === row.claimant_name;
                  return (
                    <div class="check-item">
                      <p>
                        <strong>{row.tool_code}</strong>（{statusLabel[row.status] || row.status}）
                      </p>
                      <p class="muted">认领进程首次落款：{origin || "—"}</p>
                      <p class="signer">当前落款：{row.claimant_name || "—"}</p>
                      <p class={consistent ? "pass" : "fail"}>
                        落款与认领进程{consistent ? "一致 ✓" : "不一致 ✗"}
                      </p>
                      <Show when={chain.length}>
                        <p class="hint">
                          改派链：
                          <For each={chain}>
                            {(l, i) => (
                              <span>
                                {i() > 0 ? " → " : ""}
                                {l.from_claimant_name} 改 {l.to_claimant_name}
                              </span>
                            )}
                          </For>
                        </p>
                      </Show>
                    </div>
                  );
                }}
              </For>
            </div>
          )}
        </Show>
      </section>

      {/* 改派痕迹簿 */}
      <section class="card">
        <h2>改派痕迹簿</h2>
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>刀具</th>
              <th>原落款</th>
              <th>改派后落款</th>
              <th>操作人</th>
            </tr>
          </thead>
          <tbody>
            <For each={logs()}>
              {(l) => (
                <tr>
                  <td>{fmt(l.created_at)}</td>
                  <td>{l.tool_code}</td>
                  <td class="muted">{l.from_claimant_name || "—"}</td>
                  <td class="signer">{l.to_claimant_name}</td>
                  <td>{l.operator_name}</td>
                </tr>
              )}
            </For>
          </tbody>
        </table>
        <Show when={!logs().length}>
          <p class="hint">暂无改派痕迹。</p>
        </Show>
      </section>
    </>
  );
}

export default App;
