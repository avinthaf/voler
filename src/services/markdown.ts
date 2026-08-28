import chalk from "chalk";
import Table from "tty-table";

function renderInline(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, (_, t) => chalk.bold(t))
    .replace(/\*(.+?)\*/g, (_, t) => chalk.italic(t))
    .replace(/`(.+?)`/g, (_, t) => chalk.bgBlack.white(` ${t} `));
}

function renderTable(lines: string[]): string {
  const rows = lines
    .filter((l) => !/^\|[\s:|-]+\|$/.test(l.trim()))
    .map((l) =>
      l.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim())
    );

  if (rows.length < 2) return lines.join("\n");

  const [headerRow, ...dataRows] = rows;
  const headers = (headerRow ?? []).map((h) => ({
    value: h,
    headerAlign: "left" as const,
    align: "left" as const,
    headerColor: "white",
  }));

  const data = dataRows.map((row) => row.map((cell) => renderInline(cell)));

  return Table(headers, data, { borderStyle: "solid" }).render();
}

export function renderMarkdown(text: string): string {
  const lines = text.split("\n");
  const output: string[] = [];
  let tableBuffer: string[] = [];

  const flushTable = () => {
    if (tableBuffer.length > 0) {
      output.push(renderTable(tableBuffer));
      tableBuffer = [];
    }
  };

  for (const line of lines) {
    const isTableRow = /^\|.+\|/.test(line.trim());

    if (isTableRow) {
      tableBuffer.push(line);
      continue;
    }

    flushTable();

    if (line.startsWith("### ")) { output.push(chalk.bold.yellow(line.slice(4))); continue; }
    if (line.startsWith("## "))  { output.push(chalk.bold.yellow(line.slice(3))); continue; }
    if (line.startsWith("# "))   { output.push(chalk.bold.yellow(line.slice(2))); continue; }
    if (/^[-*]{3,}$/.test(line.trim())) { output.push(chalk.dim("─".repeat(60))); continue; }

    output.push(renderInline(line));
  }

  flushTable();
  return output.join("\n");
}
