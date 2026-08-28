import { Command } from "commander";
import * as readline from "readline";
import { streamChat } from "../services/ollama.js";
import { config } from "../config.js";
import { ensureStorageDir, generateSessionId, generateSessionName, saveSession } from "../services/storage.js";
import ora from "ora";

export function registerChatCommand(program: Command) {
  program
    .command("chat")
    .description("Start an interactive chat session with a local AI model")
    .option("-m, --model <model>", "Ollama model to use", config.defaultModel)
    .action(async (options) => {
      const model: string = options.model;
      const history: { role: "user" | "assistant"; content: string }[] = [];

      ensureStorageDir();
      const sessionId = generateSessionId();
      let sessionName = "untitled";

      const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

      console.log(`Starting chat with ${model}. Type "exit" to quit.\n`);

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
          saveSession(sessionId, sessionName, history);

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
}
