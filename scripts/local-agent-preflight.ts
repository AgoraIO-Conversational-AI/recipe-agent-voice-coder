import { readFileSync } from "node:fs";
import path from "node:path";

export type LocalAgentPreflightInput = {
	platform: string;
	arch: string;
	availableCommands: ReadonlySet<string>;
	nodeVersion: string;
	envFileContents: string;
};

function envValue(contents: string, name: string): string | null {
	const line = contents
		.split(/\r?\n/)
		.find((candidate) => candidate.trimStart().startsWith(`${name}=`));
	if (!line) return null;
	const value = line.slice(line.indexOf("=") + 1).trim();
	if (
		value.length >= 2 &&
		((value.startsWith('"') && value.endsWith('"')) ||
			(value.startsWith("'") && value.endsWith("'")))
	) {
		return value.slice(1, -1);
	}
	return value;
}

export function validateLocalAgentPreflight(
	input: LocalAgentPreflightInput,
): string[] {
	if (input.platform !== "darwin") {
		throw new Error("Local coding agents require macOS");
	}
	if (input.arch !== "arm64") {
		throw new Error("Local coding agents require Apple Silicon");
	}

	for (const command of ["bun", "node", "python3", "ngrok"]) {
		if (!input.availableCommands.has(command)) {
			if (command === "ngrok") {
				throw new Error(
					"Missing required local runtime: ngrok. Install ngrok and run `ngrok config add-authtoken ...` once.",
				);
			}
			throw new Error(`Missing required local runtime: ${command}`);
		}
	}

	const match = /^v?(\d+)(?:\.\d+){0,2}$/.exec(input.nodeVersion.trim());
	if (!match) {
		throw new Error("Could not read the installed Node.js version");
	}
	if (Number(match[1]) < 22) {
		throw new Error("Local coding agents require Node.js 22 or newer");
	}

	for (const name of ["AGORA_APP_ID", "AGORA_APP_CERTIFICATE"]) {
		const value = envValue(input.envFileContents, name);
		if (!value || !/^[0-9a-f]{32}$/i.test(value)) {
			throw new Error(`Configure a usable ${name} in server/.env.local`);
		}
	}

	return [
		"macOS Apple Silicon available",
		"bun, node, python3, and ngrok available",
		"Node.js 22 or newer available",
		"Agora App ID and App Certificate configured",
	];
}

if (import.meta.main) {
	try {
		const envPath = path.join(process.cwd(), "server", ".env.local");
		const availableCommands = new Set(
			["bun", "node", "python3", "ngrok"].filter(
				(command) => Bun.which(command) !== null,
			),
		);
		const nodeResult = Bun.spawnSync(["node", "--version"]);
		const messages = validateLocalAgentPreflight({
			platform: process.platform,
			arch: process.arch,
			availableCommands,
			nodeVersion: nodeResult.success
				? nodeResult.stdout.toString().trim()
				: "",
			envFileContents: readFileSync(envPath, "utf8"),
		});
		console.log("Checking local coding Agent prerequisites...");
		for (const message of messages) console.log(`- ${message}`);
	} catch (error) {
		console.error(
			error instanceof Error
				? error.message
				: "Local coding Agent preflight failed",
		);
		process.exit(1);
	}
}
