import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const context = readFileSync(join(__dirname, "../context.md"), "utf-8");

export const systemPrompt = `${context}

Today's date is ${new Date().toLocaleDateString()}.
Your current working directory is: ${process.cwd()}
Always use absolute paths when reading or writing files.`;