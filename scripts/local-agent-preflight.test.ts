import { expect, test } from "bun:test";

import { validateLocalAgentPreflight } from "./local-agent-preflight";

const validEnv = [
	"AGORA_APP_ID=0123456789abcdef0123456789abcdef",
	"AGORA_APP_CERTIFICATE=fedcba9876543210fedcba9876543210",
].join("\n");

const validRuntime = {
	platform: "darwin",
	arch: "arm64",
	availableCommands: new Set(["bun", "node", "python3", "ngrok"]),
	nodeVersion: "v22.0.0",
	envFileContents: validEnv,
};

test("preflight accepts the certified platform and Node 22 floor", () => {
	expect(validateLocalAgentPreflight(validRuntime)).toEqual([
		"macOS Apple Silicon available",
		"bun, node, python3, and ngrok available",
		"Node.js 22 or newer available",
		"Agora App ID and App Certificate configured",
	]);
});

test("preflight rejects older Node before adapter launch", () => {
	expect(() =>
		validateLocalAgentPreflight({ ...validRuntime, nodeVersion: "v21.9.0" }),
	).toThrow("Local coding agents require Node.js 22 or newer");
	expect(() =>
		validateLocalAgentPreflight({
			...validRuntime,
			nodeVersion: "not-a-version",
		}),
	).toThrow("Could not read the installed Node.js version");
});

test("preflight retains platform, runtime, and secret-safe validation", () => {
	expect(() =>
		validateLocalAgentPreflight({ ...validRuntime, platform: "linux" }),
	).toThrow("Local coding agents require macOS");
	expect(() =>
		validateLocalAgentPreflight({
			...validRuntime,
			availableCommands: new Set(["bun", "node", "python3"]),
		}),
	).toThrow("Missing required local runtime: ngrok");

	const placeholder = [
		"AGORA_APP_ID=your_agora_app_id",
		"AGORA_APP_CERTIFICATE=top-secret",
	].join("\n");
	expect(() =>
		validateLocalAgentPreflight({
			...validRuntime,
			envFileContents: placeholder,
		}),
	).toThrow("Configure a usable AGORA_APP_ID in server/.env.local");
});
