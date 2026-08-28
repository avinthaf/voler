import { execSync } from "child_process";
import { readFileSync, writeFileSync, readdirSync } from "fs";

export async function executeTool(name: string, args: Record<string, string>):
    Promise<string> {
    switch (name) {
        case "run_bash": {
            try {
                const output = execSync(args["command"] ?? "", {
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
            try {
                writeFileSync(args["path"] ?? "", args["content"] ?? "");
                return `File written successfully: ${args["path"]}`;
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
                // strip HTML tags for readability
                return text.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0,
                    8000);
            } catch (err: any) {
                return `Error fetching URL: ${err.message}`;
            }
        }

        default:
            return `Unknown tool: ${name}`;
    }
}