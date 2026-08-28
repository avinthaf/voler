declare module "tty-table" {
  interface ColumnHeader {
    value: string;
    align?: "left" | "right" | "center";
    headerAlign?: "left" | "right" | "center";
    headerColor?: string;
    width?: number;
  }

  interface TableOptions {
    borderStyle?: "solid" | "dashed" | "none";
    width?: string | number;
  }

  function Table(
    headers: ColumnHeader[],
    rows: string[][],
    options?: TableOptions
  ): { render: () => string };

  export default Table;
}
