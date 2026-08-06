/**
 * Pi Agent SDK bridge for the Python wrapper.
 *
 * Input  : one JSON object on stdin  { "cwd": "...", "prompt": "...", "model": "..."?, "thinkingLevel": "high"?, "session_dir": "..."? }
 * Output : assistant text deltas streamed to stdout (raw characters)
 * States : one JSON line on stderr after session.prompt() has ended: the
 *          SessionStats object (session id, file, message/tool counts,
 *          tokens, cost, context usage). Nothing is emitted during the run.
 * Errors : JSON error object on stderr, exit code 1
 *
 * Uses the project-local @earendil-works/pi-coding-agent dependency (npm install).
 * Run directly with Node >= 23.6 (built-in type stripping): node agent.mts
 * Type-check with: npx tsc --noEmit
 */

import {
  createAgentSession,
  ModelRuntime,
  SessionManager,
  resolveCliModel,
  type AgentSessionEvent,
  type CreateAgentSessionOptions,
  getAgentDir,
  DefaultResourceLoader,
} from "@earendil-works/pi-coding-agent";

import { join } from "node:path";

/** Derive from SDK options so we don't need a direct dependency on pi-agent-core. */
type ThinkingLevel = NonNullable<CreateAgentSessionOptions["thinkingLevel"]>;
type Model = CreateAgentSessionOptions["model"];

interface BridgeInput {
  /** Working directory the agent operates in (required). */
  cwd: string;
  /** Prompt to send to the agent (required). */
  prompt: string;
  /** e.g. "openrouter/moonshotai/kimi-k3" or "provider/model:high". Falls back to pi settings default. */
  model?: string;
  /** off | minimal | low | medium | high | xhigh | max */
  thinkingLevel?: ThinkingLevel;
  /** Directory for session JSONL files. Defaults to <cwd>/.pi/sessions. */
  session_dir?: string;
}

function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk: string) => (data += chunk));
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

function fail(message: unknown): never {
  process.stderr.write(JSON.stringify({ error: String(message) }) + "\n");
  process.exit(1);
}

async function main(): Promise<void> {
  const raw = await readStdin();
  let input: BridgeInput;
  try {
    input = JSON.parse(raw) as BridgeInput;
  } catch (e) {
    fail(`invalid JSON input: ${(e as Error).message}`);
  }

  if (!input.cwd) fail("missing required field: cwd");
  if (!input.prompt) fail("missing required field: prompt");

  const modelRuntime = await ModelRuntime.create();

  // Resolve model. Accepts "provider/model", "model", optionally ":level" suffix.
  let model: Model;
  let thinkingLevel = input.thinkingLevel;
  if (input.model) {
    const resolved = resolveCliModel({ cliModel: input.model, modelRuntime });
    if (resolved.error) fail(`model resolution failed: ${resolved.error}`);
    model = resolved.model;
    if (resolved.thinkingLevel && !thinkingLevel) thinkingLevel = resolved.thinkingLevel;
  }

  // discover all prompts/skills from cwd/.pi/prompts, cwd/.pi/skills, etc.
  const loader = new DefaultResourceLoader({
    cwd: input.cwd,
    agentDir: getAgentDir(),
  });
  await loader.reload();

  // session directory: default is cwd/.pi/sessions
  const session_dir = input.session_dir?? join(input.cwd, ".pi", "sessions");
  const { session } = await createAgentSession({
    cwd: input.cwd,
    model,
    thinkingLevel,
    modelRuntime,
    resourceLoader: loader,
    sessionManager: SessionManager.create(input.cwd, session_dir),
  });
  try {
    session.subscribe((event: AgentSessionEvent) => {
      if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
        process.stdout.write(event.assistantMessageEvent.delta);
      }
    });

    await session.prompt(input.prompt);

    // Final session stats, emitted once after the run has ended.
    process.stderr.write(JSON.stringify(session.getSessionStats()) + "\n");

    const errorMessage = session.agent.state.errorMessage;
    if (errorMessage) fail(errorMessage);
  } finally {
    session.dispose();
  }
}

main().catch((e: unknown) => fail(e instanceof Error ? e.message : e));
