"use client";

// Mounted adaptation of week4-officebench/platform-integration/page.tsx.
// This route uses Spring flowRun instead of the standalone page's direct localhost bridge.
import { useCallback, useMemo, useRef, useState } from "react";
import VisualDiagram, { type ViewState, type VisualCanvasConfig, type VisualDiagramHandle, type VisualElementProps } from "@horsecoder/visual-core";
import { PlayCircleOutlined, ReloadOutlined } from "@ant-design/icons";
import { flowRun } from "@/src/flows/com.horsecoder.common.whuTalent.skillTesting.core/Run";
import { cases, edges, nodes } from "./frozen";
import styles from "./page.module.css";

type RunResponse = {
  case_id: string;
  execution: string;
  result: {
    status?: string;
    before?: unknown;
    after?: unknown;
    events?: unknown;
    artifacts?: unknown;
    [key: string]: unknown;
  };
};

const LABELS: Record<string, string> = {
  locate: "定位输入", classify: "拆解意图", files: "文件操作", sheets: "表格操作",
  path_guard: "路径校验", semantic_guard: "语义校验", native_guard: "原生评分", commit: "条件写回",
};
const POSITIONS: Record<string, [number, number]> = {
  locate: [60, 220], classify: [280, 220], files: [510, 70], sheets: [510, 350],
  path_guard: [760, 220], semantic_guard: [1000, 80], native_guard: [1000, 350], commit: [1250, 220],
};

function initialView(): ViewState {
  return {
    id: "officebench-week4-frozen-structure",
    elements: nodes.map((node) => ({
      id: node.id, name: LABELS[node.id] ?? node.id, type: "model",
      color: node.id.endsWith("guard") ? "#327e74" : node.id === "commit" ? "#bd6e39" : "#436b8b",
      x: POSITIONS[node.id]?.[0] ?? 0, y: POSITIONS[node.id]?.[1] ?? 0,
      select: false, locked: false, skill: node.skill,
    })),
    links: edges.map((edge) => ({
      id: `${edge.from}-${edge.to}`, name: edge.type, type: "relation",
      color: "#65858a", points: [], fromElementId: edge.from, toElementId: edge.to,
    })),
  } as ViewState;
}

function Node({ element }: VisualElementProps) {
  return <div className={styles.node}><strong>{element.state.name}</strong><small>{element.state.id}</small></div>;
}

function parseRunResponse(raw: string): RunResponse {
  const data: unknown = JSON.parse(raw);
  if (!data || typeof data !== "object" || !("case_id" in data) || !("result" in data) ||
      !data.result || typeof data.result !== "object") {
    throw new Error("后端返回的执行证据格式不正确");
  }
  return data as RunResponse;
}

export default function OfficeBenchWeek4Page() {
  const diagram = useRef<VisualDiagramHandle | null>(null);
  const attachDiagram = useCallback((handle: VisualDiagramHandle | null) => {
    diagram.current = handle;
    if (handle) handle.setView(initialView());
  }, []);
  const [caseId, setCaseId] = useState<string>(cases[0]?.id ?? "");
  const [output, setOutput] = useState<RunResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const canvasConfig = useMemo<VisualCanvasConfig>(() => ({
    toolbarConfig: [],
    elementConfig: { components: { model: { component: Node, minSize: { width: 158, height: 72 } } } },
    linkConfig: { components: { relation: { hasArrow: true, showName: false } } },
    globalConfig: { gridSize: 25 },
  }), []);

  function reload() {
    diagram.current?.setView(initialView());
    setOutput(null);
    setError("");
  }

  async function run() {
    if (!caseId || busy) return;
    setBusy(true);
    setError("");
    setOutput(null);
    try {
      const graph = diagram.current?.getView();
      if (!graph) throw new Error("图编辑器尚未就绪");
      const response = await flowRun({ structure: JSON.stringify({ case_id: caseId, graph }) });
      const raw = response.data?.value?.result;
      if (typeof raw !== "string") throw new Error("后端未返回执行证据");
      const parsed = parseRunResponse(raw);
      if (parsed.case_id !== caseId) throw new Error("后端返回的任务与所选任务不一致");
      setOutput(parsed);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "运行失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div><h1>OfficeBench 多技能编排</h1><p>Spring FlowCodeRun · 本地确定性执行</p></div>
        <div className={styles.actions}>
          <label htmlFor="case">任务</label>
          <select id="case" value={caseId} onChange={(event) => { setCaseId(event.target.value); setOutput(null); }} disabled={busy}>
            {cases.map((item) => <option key={item.id} value={item.id}>{item.id} · {item.kind}</option>)}
          </select>
          <button type="button" title="重新加载冻结结构" aria-label="重新加载冻结结构" onClick={reload} disabled={busy}><ReloadOutlined /></button>
          <button type="button" title="运行当前图" onClick={run} disabled={!caseId || busy}><PlayCircleOutlined /> {busy ? "运行中" : "运行图"}</button>
        </div>
      </header>
      <div className={styles.layout}>
        <section className={styles.canvas} aria-label="可编辑编排图"><VisualDiagram ref={attachDiagram} canvasConfig={canvasConfig} /></section>
        <aside className={styles.evidence} aria-live="polite">
          <h2>执行证据</h2>
          {error && <p role="alert" className={styles.error}>{error}</p>}
          {!output && !error && <p>选择任务后运行当前编排图。</p>}
          {output && <>
            <p><strong>{output.case_id}</strong> · {output.result.status ?? "未标记"}</p>
            <p className={styles.note}>{output.execution}</p>
            <h3>编排前</h3><pre>{JSON.stringify(output.result.before ?? null, null, 2)}</pre>
            <h3>编排后</h3><pre>{JSON.stringify(output.result.after ?? null, null, 2)}</pre>
            <h3>逐节点事件</h3><pre>{JSON.stringify(output.result.events ?? [], null, 2)}</pre>
            <h3>产物</h3><pre>{JSON.stringify(output.result.artifacts ?? [], null, 2)}</pre>
          </>}
          <p className={styles.note}>节点位置和显示名称可编辑；增删节点、更改边或技能会被冻结结构校验拒绝。编排前证据缺失不代表真实失败。</p>
        </aside>
      </div>
    </main>
  );
}
