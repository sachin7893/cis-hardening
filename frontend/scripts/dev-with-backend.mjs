import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const frontendDir = path.resolve(__dirname, "..");
const repoRoot = path.resolve(frontendDir, "..");
const venvPython = path.join(repoRoot, "venv", "Scripts", "python.exe");
const appPy = path.join(repoRoot, "app.py");
const viteCmd = path.join(frontendDir, "node_modules", ".bin", "vite.cmd");
const isWindows = os.platform() === "win32";

if (!existsSync(venvPython)) {
  console.error(`Virtual environment Python was not found at ${venvPython}`);
  process.exit(1);
}

if (!existsSync(viteCmd)) {
  console.error(`Vite executable was not found at ${viteCmd}. Run npm install in frontend first.`);
  process.exit(1);
}

const childProcesses = [];
let shuttingDown = false;

function spawnLoggedProcess(command, args, options, name) {
  const child = spawn(command, args, {
    stdio: "inherit",
    shell: false,
    ...options
  });

  childProcesses.push(child);

  child.on("exit", (code, signal) => {
    if (shuttingDown) {
      return;
    }

    if (code !== 0) {
      console.error(`${name} exited with code ${code ?? "unknown"}${signal ? ` (${signal})` : ""}.`);
      shutdown(code ?? 1);
    }
  });

  child.on("error", (error) => {
    if (shuttingDown) {
      return;
    }

    console.error(`${name} failed to start: ${error.message}`);
    shutdown(1);
  });

  return child;
}

function shutdown(exitCode = 0) {
  if (shuttingDown) {
    return;
  }

  shuttingDown = true;

  for (const child of childProcesses) {
    if (!child.killed) {
      child.kill();
    }
  }

  process.exit(exitCode);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

spawnLoggedProcess(venvPython, [appPy], { cwd: repoRoot }, "Flask backend");

if (isWindows) {
  // `.cmd` launchers need to run through `cmd.exe` when using spawn on Windows.
  spawnLoggedProcess("cmd.exe", ["/c", viteCmd], { cwd: frontendDir }, "Vite dev server");
} else {
  spawnLoggedProcess(viteCmd, [], { cwd: frontendDir }, "Vite dev server");
}
