/** QwenPaw File Browser — read-only PawApp page. */
(function () {
  var QwenPaw = window.QwenPaw;
  var APP_ID = "qwenpaw-file-browser";
  var ACTION_ID = "list-directory";
  if (!QwenPaw || !QwenPaw.host || !QwenPaw.paw) {
    console.error("[qwenpaw-file-browser] PawApp host is unavailable.");
    return;
  }

  var host = QwenPaw.host;
  var React = host.React;
  var antd = host.antd;
  var paw = QwenPaw.paw.forApp(APP_ID);
  var h = React.createElement;
  var useEffect = React.useEffect;
  var useState = React.useState;
  var Alert = antd.Alert;
  var Button = antd.Button;
  var Card = antd.Card;
  var Empty = antd.Empty;
  var Input = antd.Input;
  var Space = antd.Space;
  var Spin = antd.Spin;
  var Table = antd.Table;
  var Tag = antd.Tag;
  var Typography = antd.Typography;

  function requestId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return "file-browser-" + window.crypto.randomUUID();
    }
    return "file-browser-" + Date.now() + "-" + Math.random().toString(16).slice(2);
  }

  async function responseJson(response) {
    var payload = await response.json().catch(function () { return {}; });
    if (!response.ok) {
      var detail = payload && payload.detail;
      throw new Error(typeof detail === "string" ? detail : "request_" + response.status);
    }
    return payload;
  }

  async function directChatId(workspaceId) {
    var sessions = await paw.chatSessions.list({ agentId: workspaceId });
    var current = sessions.find(function (item) { return !item.archived; });
    if (!current) {
      current = await paw.chatSessions.create({
        agentId: workspaceId,
        name: "File Browser",
      });
    }
    if (!current.id) throw new Error("file_browser_session_unavailable");
    return current.id;
  }

  async function getTask(workspaceId, taskId) {
    var path = "/pawapps/" + encodeURIComponent(APP_ID)
      + "/workspaces/" + encodeURIComponent(workspaceId)
      + "/tasks/" + encodeURIComponent(taskId);
    var payload = await responseJson(await host.fetch(path));
    return payload.task || {};
  }

  async function waitForTask(workspaceId, taskId) {
    for (var attempt = 0; attempt < 120; attempt += 1) {
      var task = await getTask(workspaceId, taskId);
      if (["succeeded", "failed", "cancelled", "interrupted"].includes(task.status)) {
        return task;
      }
      await new Promise(function (resolve) { window.setTimeout(resolve, 250); });
    }
    throw new Error("file_browser_task_timeout");
  }

  function formatSize(value) {
    if (value === null || value === undefined) return "—";
    if (value < 1024) return value + " B";
    if (value < 1024 * 1024) return (value / 1024).toFixed(1) + " KB";
    return (value / (1024 * 1024)).toFixed(1) + " MB";
  }

  function FileBrowserPage() {
    var theme = typeof host.useTheme === "function" ? host.useTheme() : "light";
    var dark = theme === "dark";
    var selectedAgent = typeof host.useSelectedAgent === "function"
      ? host.useSelectedAgent()
      : { id: paw.host.getSelectedAgentId() };
    var workspaceId = selectedAgent.id;
    var setupRequest = new URLSearchParams(window.location.search).get("setupRequest");
    var preferenceState = useState(null);
    var preference = preferenceState[0];
    var setPreference = preferenceState[1];
    var defaultState = useState("");
    var defaultDirectory = defaultState[0];
    var setDefaultDirectory = defaultState[1];
    var directoryState = useState("");
    var directory = directoryState[0];
    var setDirectory = directoryState[1];
    var listingState = useState(null);
    var listing = listingState[0];
    var setListing = listingState[1];
    var loadingState = useState(true);
    var loading = loadingState[0];
    var setLoading = loadingState[1];
    var savingState = useState(false);
    var saving = savingState[0];
    var setSaving = savingState[1];
    var listingBusyState = useState(false);
    var listingBusy = listingBusyState[0];
    var setListingBusy = listingBusyState[1];
    var errorState = useState("");
    var error = errorState[0];
    var setError = errorState[1];

    useEffect(function () {
      var cancelled = false;
      setLoading(true);
      paw.api.get("/preferences/directory")
        .then(function (next) {
          if (cancelled) return;
          setPreference(next);
          setDefaultDirectory(next.directory || "");
        })
        .catch(function (cause) {
          if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
        })
        .finally(function () { if (!cancelled) setLoading(false); });
      return function () { cancelled = true; };
    }, [workspaceId]);

    useEffect(function () {
      var cancelled = false;
      var key = "last-directory-task:" + workspaceId;
      paw.storage.get(key, null).then(function (saved) {
        if (!saved || saved.workspace_id !== workspaceId || !saved.task_id) return null;
        return waitForTask(workspaceId, saved.task_id);
      }).then(function (task) {
        if (!cancelled && task && task.status === "succeeded" && task.text_result) {
          setListing(JSON.parse(task.text_result));
        }
      }).catch(function () {
        // A revoked grant or removed task makes the saved pointer unreadable.
      });
      return function () { cancelled = true; };
    }, [workspaceId]);

    async function saveDefault() {
      setSaving(true);
      setError("");
      try {
        var next = await paw.api.put("/preferences/directory", {
          directory: defaultDirectory,
          expected_revision: preference ? preference.revision : 0,
          setup_request_id: setupRequest || undefined,
        });
        setPreference(next);
        setDefaultDirectory(next.directory || "");
        await paw.toast("Default directory saved", "success");
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        setSaving(false);
      }
    }

    async function listDirectory() {
      setListingBusy(true);
      setError("");
      setListing(null);
      try {
        var chatId = await directChatId(workspaceId);
        var path = "/pawapps/" + encodeURIComponent(APP_ID)
          + "/workspaces/" + encodeURIComponent(workspaceId)
          + "/actions/" + encodeURIComponent(ACTION_ID) + "/tasks";
        var inputs = directory.trim() ? { directory: directory.trim() } : {};
        var dispatched = await responseJson(await host.fetch(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            request_id: requestId(),
            chat_id: chatId,
            engagement: "direct",
            inputs: inputs,
          }),
        }));
        if (dispatched.state === "blocked") {
          throw new Error(dispatched.reason || "file_browser_not_ready");
        }
        await paw.storage.set("last-directory-task:" + workspaceId, {
          workspace_id: workspaceId,
          task_id: dispatched.task.task_id,
        }).catch(function () { return undefined; });
        var task = await waitForTask(workspaceId, dispatched.task.task_id);
        if (task.status !== "succeeded") {
          throw new Error((task.recovery_reason || task.status || "file_browser_task_failed"));
        }
        setListing(JSON.parse(task.text_result));
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        setListingBusy(false);
      }
    }

    var colors = {
      page: dark ? "#0f1115" : "#f5f7fa",
      text: dark ? "#f3f4f6" : "#172033",
      muted: dark ? "#9ca3af" : "#667085",
      border: dark ? "#2b3038" : "#e5e9f0",
    };
    var columns = [
      {
        title: "Name",
        dataIndex: "name",
        key: "name",
        render: function (name, item) {
          return h(Space, null,
            h("span", null, item.type === "directory" ? "📁" : item.type === "symlink" ? "↗" : "📄"),
            h(Typography.Text, { ellipsis: true }, name));
        },
      },
      {
        title: "Type",
        dataIndex: "type",
        key: "type",
        width: 130,
        render: function (value) { return h(Tag, null, value); },
      },
      {
        title: "Size",
        dataIndex: "size_bytes",
        key: "size_bytes",
        width: 120,
        render: formatSize,
      },
    ];

    return h("main", {
      style: {
        minHeight: "100%",
        background: colors.page,
        color: colors.text,
        padding: "32px clamp(18px, 5vw, 64px)",
      },
    },
    h("div", { style: { maxWidth: 1040, margin: "0 auto" } },
      h("div", { style: { marginBottom: 24 } },
        h(Typography.Title, { level: 2, style: { marginBottom: 4 } }, "File Browser"),
        h(Typography.Text, { style: { color: colors.muted } },
          "Browse one authorized directory at a time. Listings are read-only, non-recursive, and capped at 200 entries.")),
      error ? h(Alert, {
        type: "error",
        showIcon: true,
        closable: true,
        message: error === "action_forbidden" ? "Directory access is not enabled for this agent." : "File Browser could not continue",
        description: error === "action_forbidden"
          ? h("span", null, "Enable this action and its exact directory under ",
              h("a", { href: "/settings/app-access" }, "Settings → App access"), ".")
          : error,
        onClose: function () { setError(""); },
        style: { marginBottom: 20 },
      }) : null,
      h(Card, {
        title: "Default directory",
        style: { marginBottom: 20, borderColor: colors.border },
        extra: preference && preference.available ? h(Tag, { color: "green" }, "Available") : null,
      }, loading ? h(Spin, null) : h(Space.Compact, { style: { width: "100%" } },
        h(Input, {
          value: defaultDirectory,
          placeholder: "/absolute/path/to/folder",
          onChange: function (event) { setDefaultDirectory(event.target.value); },
          onPressEnter: saveDefault,
        }),
        h(Button, {
          type: "primary",
          loading: saving,
          disabled: !defaultDirectory.trim(),
          onClick: saveDefault,
        }, "Save")),
      h(Typography.Paragraph, { style: { color: colors.muted, margin: "12px 0 0" } },
        "Used when a task omits the directory. Saving a default does not grant access; Host authorization stays separate.")),
      h(Card, { title: "List a directory", style: { borderColor: colors.border } },
        h(Space.Compact, { style: { width: "100%" } },
          h(Input, {
            value: directory,
            placeholder: "Leave empty to use the saved default",
            onChange: function (event) { setDirectory(event.target.value); },
            onPressEnter: listDirectory,
          }),
          h(Button, { type: "primary", loading: listingBusy, onClick: listDirectory }, "List")),
        listing ? h("div", { style: { marginTop: 20 } },
          h(Space, { style: { marginBottom: 12, width: "100%", justifyContent: "space-between" } },
            h(Typography.Text, { code: true, ellipsis: true }, listing.directory),
            listing.truncated ? h(Tag, { color: "gold" }, "First " + listing.limit + " entries") : h(Tag, null, listing.entries.length + " entries")),
          h(Table, {
            rowKey: "name",
            size: "small",
            pagination: false,
            columns: columns,
            dataSource: listing.entries,
            locale: { emptyText: h(Empty, { description: "This directory is empty" }) },
            scroll: { x: 560 },
          })) : null)));
  }

  paw.ui.registerPage({
    path: "/apps/" + APP_ID,
    label: "File Browser",
    icon: "📁",
    component: FileBrowserPage,
  });
})();
