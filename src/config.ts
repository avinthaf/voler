import "dotenv/config";

export const config = {
    defaultModel: process.env["OLLAMA_MODEL"] ?? "gemma4:e4b",
};