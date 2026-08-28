import { Ollama } from "ollama";
import type { Ora } from "ora";
import { renderMarkdown } from "./markdown.js";
import { toolDefinitions } from "../tools/definitions.js";
import { executeTool } from "../tools/executor.js";

const client = new Ollama();

export async function streamChat(
  messages: { role: string; content: string }[],
  model: string,
  spinner?: Ora
): Promise<string> {
  let currentMessages = [...messages];

  while (true) {
    const response = await client.chat({
      model,
      messages: currentMessages,
      tools: toolDefinitions,
    });

    currentMessages.push(response.message);

    if (!response.message.tool_calls?.length) {
      spinner?.stop();
      const content = response.message.content ?? "";
      process.stdout.write(renderMarkdown(content));
      process.stdout.write("\n\n");
      return content;
    }

    if (spinner) spinner.text = "Using tools...";

    for (const call of response.message.tool_calls) {
      const toolName = call.function.name;
      const toolArgs = call.function.arguments as Record<string, string>;

      if (spinner) spinner.text = `Running: ${toolName}...`;
      const result = await executeTool(toolName, toolArgs);

      currentMessages.push({
        role: "tool",
        content: result,
      });
    }
  }
}
