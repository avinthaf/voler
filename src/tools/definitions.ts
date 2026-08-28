export const toolDefinitions = [
    {
        type: "function",
        function: {
            name: "run_bash",
            description: "Execute a bash command and return the output. Use for running code, tests, git commands, etc.",
            parameters: {
                type: "object",
                required: ["command"],
                properties: {
                    command: { type: "string", description: "The bash command to execute" },
                },
            },
        },
    },
    {
        type: "function",
        function: {
            name: "read_file",
            description: "Read the contents of a file from disk",
            parameters: {
                type: "object",
                required: ["path"],
                properties: {
                    path: { type: "string", description: "The file path to read" },
                },
            },
        },
    },
    {
        type: "function",
        function: {
            name: "write_file",
            description: "Write content to a file on disk",
            parameters: {
                type: "object",
                required: ["path", "content"],
                properties: {
                    path: { type: "string", description: "The file path to write to" },
                    content: { type: "string", description: "The content to write" },
                },
            },
        },
    },
    {
        type: "function",
        function: {
            name: "list_directory",
            description: "List files and folders in a directory",
            parameters: {
                type: "object",
                required: ["path"],
                properties: {
                    path: { type: "string", description: "The directory path to list" },
                },
            },
        },
    },
    {
        type: "function",
        function: {
            name: "web_fetch",
            description: "Fetch the content of a URL. Use for reading documentation, READMEs, or any web page.",
            parameters: {
                type: "object",
                required: ["url"],
                properties: {
                    url: { type: "string", description: "The URL to fetch" },
                },
            },
        },
    },
];