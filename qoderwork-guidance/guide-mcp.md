# MCP Server Management Guide

This guide covers managing MCP (Model Context Protocol) servers through the QoderWork Connector. MCP servers are managed under two sub-namespaces of `connector`:

- **Market MCP** (`connector.market.*`): Built-in MCP servers (e.g. Notion, GitHub, Linear) that ship with QoderWork.
- **Custom MCP** (`connector.custom.*`): User-added MCP servers (stdio or SSE/HTTP).

## Keys

When the user says "open" or Chinese "打开" for an MCP server, treat it as enabling/installing the server by default. Use `open` only for explicit UI navigation such as opening the Connector settings page or a server detail page.

| Key | Actions | Description |
|-----|---------|-------------|
| `qoderwork.settings.connector.market` | query, open | Market (built-in) MCP servers list. Supports keyword param. |
| `qoderwork.settings.connector.market.{name}` | query, open, enable, disable, install, uninstall, execute | Single market MCP server (install/uninstall = enable/disable) |
| `qoderwork.settings.connector.custom` | query, open, add | Custom (user-added) MCP servers list. Supports keyword param and add action. |
| `qoderwork.settings.connector.custom.{name}` | query, open, update, enable, disable, remove, execute | Single custom MCP server CRUD |

---

## Market MCP Servers

Market MCP servers are built-in servers that ship with QoderWork. They can be installed (enabled) or uninstalled (disabled) but not removed or reconfigured.

### List Market MCP Servers

```
mcp__qw-builtin__qw_query({ key: "qoderwork.settings.connector.market" })
```

Supports keyword filtering:

```
mcp__qw-builtin__qw_query({ key: "qoderwork.settings.connector.market", params: { keyword: "notion" } })
```

**Response structure:**

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "name": "notion",
        "displayName": "Notion",
        "enabled": true,
        "status": "connected",
        "key": "qoderwork.settings.connector.market.notion"
      }
    ],
    "totalCount": 10,
    "enabledCount": 3
  }
}
```

### Query Single Market Server

```
mcp__qw-builtin__qw_query({ key: "qoderwork.settings.connector.market.notion" })
```

**Response includes:**

- `name`, `displayName`, `enabled`, `status`
- `tools[]`: Array of `{ name, description }` for all tools provided by this server
- `error`: Error message if connection failed
- `authUrl`: OAuth URL if the server requires authentication
- `key`: The full key path for this server

### Install / Uninstall (Enable / Disable)

`install` and `uninstall` are semantic aliases for `enable` and `disable`, designed for market MCP servers:

```
mcp__qw-builtin__qw_action({
  key: "qoderwork.settings.connector.market.notion",
  action: "install"
})
```

```
mcp__qw-builtin__qw_action({
  key: "qoderwork.settings.connector.market.notion",
  action: "uninstall"
})
```

You can also use `enable` / `disable` directly — they are equivalent.

### Execute (OAuth Authentication)

Some market servers require OAuth. Use execute with `operation: "auth"` to start the OAuth flow:

```
mcp__qw-builtin__qw_action({
  key: "qoderwork.settings.connector.market.notion",
  action: "execute",
  params: { operation: "auth" }
})
```

To reset OAuth credentials:

```
mcp__qw-builtin__qw_action({
  key: "qoderwork.settings.connector.market.notion",
  action: "execute",
  params: { operation: "reset" }
})
```

---

## Custom MCP Servers

Custom MCP servers are user-added servers configured via stdio (command + args) or SSE/HTTP (URL).

### List Custom MCP Servers

```
mcp__qw-builtin__qw_query({ key: "qoderwork.settings.connector.custom" })
```

Supports keyword filtering:

```
mcp__qw-builtin__qw_query({ key: "qoderwork.settings.connector.custom", params: { keyword: "filesystem" } })
```

### Add a New Custom Server

#### Stdio-based server (command + args)

```
mcp__qw-builtin__qw_action({
  key: "qoderwork.settings.connector.custom",
  action: "add",
  params: {
    name: "my-mcp-server",
    config: {
      command: "npx",
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
      env: {
        SOME_VAR: "value"
      }
    }
  }
})
```

#### SSE/Streamable HTTP server (URL)

```
mcp__qw-builtin__qw_action({
  key: "qoderwork.settings.connector.custom",
  action: "add",
  params: {
    name: "remote-server",
    config: {
      url: "https://example.com/mcp/sse"
    }
  }
})
```

**Required params:**

| Param | Type | Description |
|-------|------|-------------|
| `name` | string | Unique server identifier |
| `config` | object | Server configuration (see below) |

**Config fields (stdio):**

| Field | Type | Description |
|-------|------|-------------|
| `command` | string | Executable command (e.g. `npx`, `node`, `python`) |
| `args` | string[] | Command arguments |
| `env` | object | Optional environment variables |

**Config fields (SSE/HTTP):**

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Server endpoint URL |

After adding, the response includes the server's key:

```json
{
  "success": true,
  "data": { "name": "my-mcp-server", "key": "qoderwork.settings.connector.custom.my-mcp-server" }
}
```

The MCP pool automatically reloads and attempts to connect. Check the status with a follow-up query.

### Query Server Detail

```
mcp__qw-builtin__qw_query({ key: "qoderwork.settings.connector.custom.my-server" })
```

**Response includes:**

- `name`, `enabled`, `status`
- `tools[]`: Array of `{ name, description }` for all tools provided by this server
- `error`: Error message if connection failed
- `config`: Safe configuration (command, args, url, env key names -- no secrets)

### Enable / Disable a Server

```
mcp__qw-builtin__qw_action({
  key: "qoderwork.settings.connector.custom.my-server",
  action: "enable"
})
```

```
mcp__qw-builtin__qw_action({
  key: "qoderwork.settings.connector.custom.my-server",
  action: "disable"
})
```

Toggling triggers an automatic MCP pool reload in the background.

### Update Server Configuration

Replace the server's config while preserving internal fields (`enabled`, `_builtinId`, `_oauth`):

```
mcp__qw-builtin__qw_action({
  key: "qoderwork.settings.connector.custom.my-server",
  action: "update",
  params: {
    config: {
      command: "npx",
      args: ["-y", "updated-server@latest"]
    }
  }
})
```

The update merges the new config with preserved internal fields, then triggers a pool reload.

### Remove a Server

```
mcp__qw-builtin__qw_action({
  key: "qoderwork.settings.connector.custom.my-server",
  action: "remove"
})
```

Permanently removes the server from configuration and triggers a pool reload.

### Execute (OAuth Authentication)

Custom servers that support OAuth can use execute with `operation: "auth"`:

```
mcp__qw-builtin__qw_action({
  key: "qoderwork.settings.connector.custom.my-server",
  action: "execute",
  params: { operation: "auth" }
})
```

---

## Workflow: Add and Verify a New Custom Server

1. **Add** the server:
   ```
   action({ key: "qoderwork.settings.connector.custom", action: "add", params: {
     name: "filesystem",
     config: { command: "npx", args: ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/docs"] }
   }})
   ```

2. **Wait** a moment for the connection to establish (the pool reloads asynchronously).

3. **Verify** the connection and available tools:
   ```
   query({ key: "qoderwork.settings.connector.custom.filesystem" })
   ```
   Check that `status` is `"connected"` and `tools` lists the expected tools.

4. If `status` is `"error"`, check the `error` field for details. Common issues:
   - Command not found: Verify the `command` path
   - Connection refused: For SSE servers, verify the URL is accessible
   - Missing environment variables: Add required env vars to the config

## Workflow: Troubleshoot a Failing Server

1. **Query** the server to get error details:
   ```
   query({ key: "qoderwork.settings.connector.custom.my-server" })
   ```

2. **If config needs fixing**, update it:
   ```
   action({ key: "qoderwork.settings.connector.custom.my-server", action: "update", params: { config: { ... } } })
   ```

3. **If server needs restart**, disable then re-enable:
   ```
   action({ key: "qoderwork.settings.connector.custom.my-server", action: "disable" })
   action({ key: "qoderwork.settings.connector.custom.my-server", action: "enable" })
   ```

4. **Verify** status after fix:
   ```
   query({ key: "qoderwork.settings.connector.custom.my-server" })
   ```

## Workflow: Install a Market MCP Server

1. **Browse** available market servers:
   ```
   query({ key: "qoderwork.settings.connector.market" })
   ```

2. **Install** the desired server:
   ```
   action({ key: "qoderwork.settings.connector.market.notion", action: "install" })
   ```

3. **If OAuth is required**, start the auth flow:
   ```
   action({ key: "qoderwork.settings.connector.market.notion", action: "execute", params: { operation: "auth" } })
   ```

4. **Verify** connection:
   ```
   query({ key: "qoderwork.settings.connector.market.notion" })
   ```

---

## Notes

- Custom server names must be unique.
- Market MCP servers cannot be removed or reconfigured -- only installed (enabled) or uninstalled (disabled).
- The `env` field in query responses only shows key names (not values) to avoid leaking secrets.
- All add/update/remove/toggle operations trigger an asynchronous pool reload. The server may take a few seconds to connect after changes.
- **Status values:** `connected`, `connecting`, `disconnected`, `error`, `pending`, `disabled`, `unknown`.
