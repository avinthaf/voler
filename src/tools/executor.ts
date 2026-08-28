import { execSync } from "child_process";
import { readFileSync, writeFileSync, readdirSync } from "fs";
import * as readline from "readline";
import chalk from "chalk";

async function confirm(question: string): Promise<boolean> {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => {
    rl.question(question, (answer) => {
      rl.close();
      resolve(answer.trim().toLowerCase() === "y");
    });
  });
}

export async function executeTool(name: string, args: Record<string, string>): Promise<string> {
  switch (name) {
    case "run_bash": {
      const command = args["command"] ?? "";
      process.stdout.write(chalk.yellow(`\n⚡ Run command: ${chalk.bold(command)}\n`));
      const ok = await confirm(chalk.yellow("Allow? (y/n): "));
      if (!ok) return "User denied the command.";
      try {
        const output = execSync(command, {
          encoding: "utf-8",
          timeout: 60000,
          stdio: ["pipe", "pipe", "pipe"],
        });
        return output || "(no output)";
      } catch (err: any) {
        return `Error: ${err.stderr ?? err.message}`;
      }
    }

    case "read_file": {
      try {
        return readFileSync(args["path"] ?? "", "utf-8");
      } catch (err: any) {
        return `Error reading file: ${err.message}`;
      }
    }

    case "write_file": {
      const path = args["path"] ?? "";
      const content = args["content"] ?? "";
      process.stdout.write(chalk.yellow(`\n📝 Write file: ${chalk.bold(path)}\n`));
      process.stdout.write(chalk.dim("--- content preview ---\n"));
      process.stdout.write(content.slice(0, 500) + (content.length > 500 ? "\n..." : "") + "\n");
      process.stdout.write(chalk.dim("---\n"));
      const ok = await confirm(chalk.yellow("Allow? (y/n): "));
      if (!ok) return "User denied the file write.";
      try {
        writeFileSync(path, content);
        return `File written successfully: ${path}`;
      } catch (err: any) {
        return `Error writing file: ${err.message}`;
      }
    }

    case "list_directory": {
      try {
        const entries = readdirSync(args["path"] ?? ".", { withFileTypes: true });
        return entries
          .map((e) => (e.isDirectory() ? `[dir]  ${e.name}` : `[file] ${e.name}`))
          .join("\n");
      } catch (err: any) {
        return `Error listing directory: ${err.message}`;
      }
    }

    case "web_fetch": {
      try {
        const res = await fetch(args["url"] ?? "");
        const text = await res.text();
        return text.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 8000);
      } catch (err: any) {
        return `Error fetching URL: ${err.message}`;
      }
    }

    default:
      return `Unknown tool: ${name}`;
  }
}
