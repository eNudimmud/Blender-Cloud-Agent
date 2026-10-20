# MCP-for-Blender integration assessment

Inspected 2026-10-20 at upstream commit `98b991c8daf91ab9d5451ee6b923d89367f733a5`.
No upstream code was installed, executed, or copied into the MVP. No upstream paid provider was called.

## Evidence and decision

- [`BlenderMCPServer.start()`](https://github.com/ahujasid/mcp-for-blender/blob/98b991c8daf91ab9d5451ee6b923d89367f733a5/addon.py#L1302) explicitly refuses `bpy.app.background`. The live bridge depends on Blender's UI/timer event loop. It is not a drop-in backend for our `blender --background` job runner. Xvfb with a GUI is a separate architecture, not headless equivalence.
- [`execute_code()`](https://github.com/ahujasid/mcp-for-blender/blob/98b991c8daf91ab9d5451ee6b923d89367f733a5/addon.py#L2286) uses Python `exec` inside Blender. The addon socket dispatch table includes that command. A model must never have an API route to this socket.
- The upstream MCP server has an [optional AST safe mode](https://github.com/ahujasid/mcp-for-blender/blob/98b991c8daf91ab9d5451ee6b923d89367f733a5/src/blender_mcp/safe_mode.py#L72), enabled by `BLENDER_MCP_SAFE_MODE`. It is off unless explicitly enabled. Its existence does not turn arbitrary Python into an OS security boundary, and a direct addon connection bypasses the MCP server's check.
- The bridge defaults to `localhost:9876`; the inspected socket dispatch path has no user authentication or workspace authorization. Loopback reduces exposure, but publishing that port would grant a code execution surface.
- Provider integrations include downloads and external generation (Meshy, Hyper3D/Rodin, Hunyuan3D, etc.). These cannot enter our no-network worker or bypass a spending gate.
- Upstream [telemetry documentation](https://github.com/ahujasid/mcp-for-blender/blob/98b991c8daf91ab9d5451ee6b923d89367f733a5/README.md#telemetry-control) distinguishes anonymous usage collection from opt-in content collection. A future spike must set `DISABLE_TELEMETRY=true`; do not assume the consent checkbox disables every network event.

**Decision:** retain our deterministic headless executor. MCP-for-Blender is an optional future interoperability spike, not a runtime dependency of this MVP. `/v1/capabilities` reports `mcp_enabled=false`.

## Safe future route

Expose a narrow MCP facade over our authenticated HTTP API: read project, propose typed scene changes, confirm an already reviewed proposal, check job, fetch an artifact. Its transport and identities need independent review. Require request IDs and expected revisions on every mutation. The facade must not expose upstream `execute_blender_code`, free-form file paths, import URLs, add-on installation, telemetry, or provider calls.

If advanced upstream observation tools become necessary, put a pinned fork in a separate, expendable worker pool. Remove arbitrary Python dispatch and provider handlers at the addon level, use an authenticated private channel, disable telemetry and all egress, enforce CPU/RAM/time/output bounds, and generate observations from fixed trusted scripts. Verify the GUI/event-loop behavior independently. Never connect that experimental pool to the API's filesystem, token, or another owner's workspace.

## What is and is not validated

The source-level compatibility/security assessment is complete. The current typed headless path is tested. No MCP transport, upstream addon, Xvfb session, upstream model generation, or advanced Blender tool compatibility has been validated. Upstream is MIT-licensed; any future copied code needs the original notice and license.
