import { createSignal, onCleanup, onMount, Show, For } from "solid-js";
import {
  fetchClaimants,
  fetchReassignments,
  fetchSubmissions,
  reassignSubmission,
} from "./api";

const statusLabel = {
  pending: "待复核",
  processing: "复核中",
  done: "已完成",
};

const TABS = [
  { key: "inflight", label: "在途改派" },
  { key: "signed", label: "已落款清单" },
  { key: "log", label: "改派痕迹簿" },
];

export default function SignoffDesk(props) {
  const [tab, setTab] = createSignal("inflight");
  const [claimants, setClaimants] = createSignal([]);
  const [rows, setRows] = createSignal([]);
  const [logs, setLogs] = createSignal([]);
  const [error, setError] = createSignal("");
  const [busy, setBusy] = createSignal(false);

  // 已落款清单筛选：按人 + 刀号核对。
  const [personFilter, setPersonFilter] = createSignal("");
  const [toolFilter, setToolFilter] = createSignal("");
  // 痕迹簿按人筛。
  const [logPersonFilter, setLogPersonFilter] = createSignal("");

  // 每条在途单选中的改派目标与备注。
  const [targets, setTargets] = createSignal({});
  const [notes, setNotes] = createSignal({});

  async function loadClaimants() {
    try {
      setClaimants(await fetchClaimants());
    } catch (e) {
      setError(e.message);
    }
  }

  async function loadRows() {
    try {
      if (tab() === "inflight") {
        setRows(await fetchSubmissions({ status: "processing" }));
      } else if (tab() === "signed") {
        const data = await fetchSubmissions({
          claimant_id: personFilter(),
          tool_code: toolFilter(),
        });
        // “已落款清单”只列已有认领人落款的单（复核中/已完成），待复核未落款不展示。
        setRows(data.filter((r) => r.claimant_name));
      }
    } catch (e) {
      setError(e.message);
    }
  }

  async function loadLogs() {
    try {
      setLogs(await fetchReassignments(logPersonFilter()));
    } catch (e) {
      setError(e.message);
    }
  }

  function targetFor(row) {
    return targets()[row.id] ?? "";
  }
  function noteFor(row) {
    return notes()[row.id] ?? "";
  }

  async function handleReassign(row) {
    const toId = Number(targetFor(row));
    if (!toId) {
      setError("请先选择改派目标认领名");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await reassignSubmission(row.id, toId, noteFor(row));
      setNotes((m) => ({ ...m, [row.id]: "" }));
      await Promise.all([loadRows(), loadLogs()]);
    } catch (e) {
      // 常见：与办结撞车（该单已办结）或已被他人改派。
      setError(e.message);
      await loadRows();
    } finally {
      setBusy(false);
    }
  }

  let timer;
  onMount(async () => {
    await loadClaimants();
    await Promise.all([loadRows(), loadLogs()]);
    // 轮询：能看到新单切入复核中时的认领人，以及改派后办结落款换人。
    timer = setInterval(() => {
      loadRows();
      loadLogs();
    }, 3000);
  });
  onCleanup(() => clearInterval(timer));

  async function switchTab(key) {
    setTab(key);
    setError("");
    if (key === "log") await loadLogs();
    else await loadRows();
  }

  const canWrite = () => props.user.can_write;

  return (
    <section class="card">
      <div class="toolbar">
        <h2>落款台</h2>
        <div class="tabs">
          <For each={TABS}>
            {(t) => (
              <button
                type="button"
                class={tab() === t.key ? "" : "ghost"}
                onClick={() => switchTab(t.key)}
              >
                {t.label}
              </button>
            )}
          </For>
        </div>
      </div>

      <Show when={error()}>
        <div class="banner error">{error()}</div>
      </Show>

      {/* 在途改派：仅复核中、未结清的单可转交另一认领名 */}
      <Show when={tab() === "inflight"}>
        <p class="hint">
          仅「复核中」未结清的单可改派；已办结的单不允许改派。改派与办结撞车时，办结先成则改派失败，不会留下半截换人。
        </p>
        <table>
          <thead>
            <tr>
              <th>刀具</th>
              <th>刀补 µm</th>
              <th>当前认领人（落款）</th>
              <th>认领时间</th>
              <Show when={canWrite()}>
                <th>改派给</th>
                <th>备注</th>
                <th></th>
              </Show>
            </tr>
          </thead>
          <tbody>
            <For each={rows()}>
              {(row) => (
                <tr>
                  <td>{row.tool_code}</td>
                  <td>{row.offset_um}</td>
                  <td>
                    <strong>{row.claimant_name || "—"}</strong>
                  </td>
                  <td>
                    {row.claimed_at ? new Date(row.claimed_at).toLocaleString() : "—"}
                  </td>
                  <Show when={canWrite()}>
                    <td>
                      <select
                        value={targetFor(row)}
                        onChange={(e) =>
                          setTargets((m) => ({ ...m, [row.id]: e.currentTarget.value }))
                        }
                      >
                        <option value="">选择认领名…</option>
                        <For each={claimants()}>
                          {(c) => (
                            <option
                              value={c.id}
                              disabled={c.id === row.claimant_id}
                            >
                              {c.name}
                            </option>
                          )}
                        </For>
                      </select>
                    </td>
                    <td>
                      <input
                        placeholder="可选"
                        value={noteFor(row)}
                        onInput={(e) =>
                          setNotes((m) => ({ ...m, [row.id]: e.currentTarget.value }))
                        }
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        disabled={busy()}
                        onClick={() => handleReassign(row)}
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
        <Show when={!rows().length}>
          <p class="hint">当前没有在途（复核中）的单。</p>
        </Show>
        <Show when={!canWrite()}>
          <p class="hint">复核侧只读：可查看落款，不能改派。</p>
        </Show>
      </Show>

      {/* 已落款清单：按人筛 + 刀号核对落款与认领进程一致 */}
      <Show when={tab() === "signed"}>
        <form
          class="form inline"
          onSubmit={(e) => {
            e.preventDefault();
            loadRows();
          }}
        >
          <label>
            按认领人筛
            <select
              value={personFilter()}
              onChange={(e) => setPersonFilter(e.currentTarget.value)}
            >
              <option value="">全部</option>
              <For each={claimants()}>
                {(c) => <option value={c.id}>{c.name}</option>}
              </For>
            </select>
          </label>
          <label>
            刀号核对
            <input
              placeholder="如 T01"
              value={toolFilter()}
              onInput={(e) => setToolFilter(e.currentTarget.value)}
            />
          </label>
          <button type="button" class="ghost" onClick={loadRows}>
            查询
          </button>
        </form>
        <p class="hint">
          落款直接取自认领进程写入的同一列；改派后这里同步显示新名，可按刀号核对落款是否与认领进程一致。
        </p>
        <table>
          <thead>
            <tr>
              <th>刀具</th>
              <th>刀补 µm</th>
              <th>状态</th>
              <th>结论</th>
              <th>落款（认领人）</th>
              <th>一致性</th>
              <th>复核时间</th>
            </tr>
          </thead>
          <tbody>
            <For each={rows()}>
              {(row) => (
                <tr>
                  <td>{row.tool_code}</td>
                  <td>{row.offset_um}</td>
                  <td>{statusLabel[row.status] || row.status}</td>
                  <td
                    class={
                      row.verdict === "合格"
                        ? "pass"
                        : row.verdict === "超差"
                        ? "fail"
                        : ""
                    }
                  >
                    {row.verdict || "—"}
                  </td>
                  <td>
                    <strong>{row.claimant_name || "—"}</strong>
                  </td>
                  <td>
                    {row.claimant_name ? (
                      <span class="badge ok">落款=认领</span>
                    ) : (
                      <span class="badge">未认领</span>
                    )}
                  </td>
                  <td>
                    {row.reviewed_at
                      ? new Date(row.reviewed_at).toLocaleString()
                      : "—"}
                  </td>
                </tr>
              )}
            </For>
          </tbody>
        </table>
        <Show when={!rows().length}>
          <p class="hint">无匹配记录。</p>
        </Show>
      </Show>

      {/* 改派痕迹簿：只读，可按人筛 */}
      <Show when={tab() === "log"}>
        <form
          class="form inline"
          onSubmit={(e) => {
            e.preventDefault();
            loadLogs();
          }}
        >
          <label>
            按认领人筛
            <select
              value={logPersonFilter()}
              onChange={(e) => setLogPersonFilter(e.currentTarget.value)}
            >
              <option value="">全部</option>
              <For each={claimants()}>
                {(c) => <option value={c.id}>{c.name}</option>}
              </For>
            </select>
          </label>
          <button type="button" class="ghost" onClick={loadLogs}>
            查询
          </button>
        </form>
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>刀具</th>
              <th>原认领人</th>
              <th>改派给</th>
              <th>操作人</th>
              <th>备注</th>
            </tr>
          </thead>
          <tbody>
            <For each={logs()}>
              {(l) => (
                <tr>
                  <td>{new Date(l.created_at).toLocaleString()}</td>
                  <td>{l.tool_code}</td>
                  <td>{l.from_name || "—"}</td>
                  <td>
                    <strong>{l.to_name}</strong>
                  </td>
                  <td>{l.operator_name}</td>
                  <td>{l.note || "—"}</td>
                </tr>
              )}
            </For>
          </tbody>
        </table>
        <Show when={!logs().length}>
          <p class="hint">暂无改派痕迹。</p>
        </Show>
      </Show>
    </section>
  );
}
