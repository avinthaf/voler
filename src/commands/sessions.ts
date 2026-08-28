import { Command } from "commander";
import { listSessions, loadSession, generateSessionName, saveSession, deleteSession, clearSessions } from "../services/storage.js";
import { streamChat } from "../services/ollama.js";
import { renderMarkdown } from "../services/markdown.js";
import { config } from "../config.js";
import * as readline from "readline";
import ora from "ora";
import { select } from "@inquirer/prompts";

export function registerSessionsCommand(program: Command) {
  const sessions = program.command("sessions").description("Manage chat sessions");

  sessions
    .command("list")
    .description("List and select a past chat session to resume")
    .option("-m, --model <model>", "Ollama model to use", config.defaultModel)
    .action(async (options) => {
      const all = listSessions();
      if (all.length === 0) {
        console.log("No sessions found.");
        return;
      }

      const id = await select({
        message: "Select a session to resume:",
        choices: all.map((s) => ({ name: `${s.name}  (${s.id})`, value: s.id })),
      });

      const model: string = options.model;
      const session = loadSession(id);
      const history = session.messages as { role: "user" | "assistant"; content: string }[];

      console.log(`\nResuming "${session.name}"\n`);

      history.forEach((msg) => {
        if (msg.role === "system") return;
        if (msg.role === "user") {
          console.log(msg.content + "\n");
        } else {
          process.stdout.write(renderMarkdown(msg.content));
          process.stdout.write("\n\n");
        }
      });

      const sessionId = id;
      let sessionName = session.name;

      const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

      process.on("SIGINT", () => {
        saveSession(sessionId, sessionName, history);
        console.log("\nSession saved. Goodbye.");
        rl.close();
        process.exit(0);
      });

      const ask = () => {
        rl.question("", async (input) => {
          const trimmed = input.trim();
          if (trimmed.toLowerCase() === "exit") {
            saveSession(sessionId, sessionName, history);
            console.log("Session saved. Goodbye.");
            rl.close();
            return;
          }
          if (!trimmed) { ask(); return; }

          history.push({ role: "user", content: trimmed });

          process.stdout.write("\n");
          const spinner = ora("Thinking...").start();
          const response = await streamChat(history, model, spinner);
          history.push({ role: "assistant", content: response });
          saveSession(sessionId, sessionName, history);

          ask();
        });
      };

      ask();
    });

  sessions
    .command("resume <id>")
    .description("Resume a past chat session")
    .option("-m, --model <model>", "Ollama model to use", config.defaultModel)
    .action(async (id, options) => {
      const model: string = options.model;
      const session = loadSession(id);
      const history = session.messages as { role: "user" | "assistant"; content: string }[];

      console.log(`Resuming "${session.name}" (${history.length} messages)\n`);

      history.forEach((msg) => {
        if (msg.role === "system") return;
        if (msg.role === "user") {
          console.log(msg.content + "\n");
        } else {
          process.stdout.write(renderMarkdown(msg.content));
          process.stdout.write("\n\n");
        }
      });

      const sessionId = id;
      let sessionName = session.name;

      const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

      process.on("SIGINT", () => {
        saveSession(sessionId, sessionName, history);
        console.log("\nSession saved. Goodbye.");
        rl.close();
        process.exit(0);
      });

      const ask = () => {
        rl.question("", async (input) => {
          const trimmed = input.trim();
          if (trimmed.toLowerCase() === "exit") {
            saveSession(sessionId, sessionName, history);
            console.log("Session saved. Goodbye.");
            rl.close();
            return;
          }
          if (!trimmed) { ask(); return; }

          if (history.filter((m) => m.role === "user").length === 0) {
            sessionName = generateSessionName(trimmed);
          }

          history.push({ role: "user", content: trimmed });

          process.stdout.write("\n");
          const spinner = ora("Thinking...").start();
          const response = await streamChat(history, model, spinner);
          history.push({ role: "assistant", content: response });
          saveSession(sessionId, sessionName, history);

          ask();
        });
      };

      ask();
    });

  sessions
    .command("delete <id>")
    .description("Delete a specific session")
    .action((id) => {
      try {
        deleteSession(id);
        console.log(`Session ${id} deleted.`);
      } catch {
        console.error(`Session not found: ${id}`);
      }
    });

  sessions
    .command("clear")
    .description("Delete all sessions")
    .action(() => {
      const count = clearSessions();
      console.log(`Deleted ${count} session${count !== 1 ? "s" : ""}.`);
    });
}
