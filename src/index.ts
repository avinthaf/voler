#!/usr/bin/env node
import {Command} from "commander";
import { registerChatCommand } from "./commands/chat.js";
import { registerSessionsCommand } from "./commands/sessions.js";

const program = new Command();

program
    .name("voler")
    .description("Local AI Assistant")
    .version("0.1.0");

registerChatCommand(program);
registerSessionsCommand(program);

program.parse();