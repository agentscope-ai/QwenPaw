//! Native console polling continues while the WebView is hidden in the tray.

use std::{
    collections::HashSet,
    fs::{self, OpenOptions},
    io::ErrorKind,
    path::{Path, PathBuf},
    sync::Mutex,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use crate::notification_delivery;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use tauri::{Emitter, Manager};

const POLL_INTERVAL: Duration = Duration::from_millis(2500);
const PUSH_EVENT: &str = "qwenpaw:console-push";

#[derive(Clone, Deserialize, Serialize)]
struct Approval {
    request_id: String,
    #[serde(default)]
    root_session_id: Option<String>,
    #[serde(default)]
    agent_id: Option<String>,
    #[serde(default)]
    owner_agent_id: Option<String>,
    tool_name: String,
    tool_display_name: Option<String>,
    created_at: f64,
    timeout_seconds: f64,
    #[serde(flatten)]
    rest: Map<String, Value>,
}

impl Approval {
    fn expires_at(&self) -> f64 {
        self.created_at + self.timeout_seconds
    }

    fn notification_target(&self) -> notification_delivery::ApprovalNotificationTarget {
        notification_delivery::ApprovalNotificationTarget {
            request_id: self.request_id.clone(),
            root_session_id: self.root_session_id.clone(),
            agent_id: self
                .owner_agent_id
                .as_ref()
                .filter(|id| !id.is_empty())
                .or(self.agent_id.as_ref())
                .cloned(),
        }
    }
}

#[derive(Clone, Deserialize, Serialize)]
struct Snapshot {
    messages: Vec<Value>,
    pending_approvals: Vec<Approval>,
}

#[derive(Clone, Serialize)]
struct PushEvent<'a> {
    generation: u64,
    snapshot: &'a Snapshot,
}

#[derive(Clone, Default)]
struct Preferences {
    enabled: bool,
    title: String,
    body: String,
}

#[derive(Default)]
struct Polling {
    generation: u64,
    client_id: String,
    client_epoch: u64,
    request_seq: u64,
    task: Option<tauri::async_runtime::JoinHandle<()>>,
}

impl Polling {
    fn claim_start(&mut self, client_id: &str, client_epoch: u64, request_seq: u64) -> bool {
        if client_epoch < self.client_epoch
            || (client_epoch == self.client_epoch
                && self.client_id == client_id
                && request_seq <= self.request_seq)
        {
            return false;
        }
        self.client_id = client_id.to_owned();
        self.client_epoch = client_epoch;
        self.request_seq = request_seq;
        true
    }
}

#[derive(Default)]
pub(crate) struct NotificationState {
    polling: Mutex<Polling>,
    preferences: Mutex<Preferences>,
}

#[derive(Default)]
struct ApprovalTracker {
    seeded: bool,
    known: HashSet<String>,
}

impl ApprovalTracker {
    fn fresh<'a>(&mut self, approvals: &'a [Approval], now: f64) -> Vec<&'a Approval> {
        let pending: Vec<_> = approvals.iter().filter(|a| a.expires_at() > now).collect();
        let pending_ids: HashSet<_> = pending.iter().map(|a| &a.request_id).collect();
        if !self.seeded {
            self.seeded = true;
            self.known = pending_ids.into_iter().cloned().collect();
            return Vec::new();
        }
        self.known.retain(|id| pending_ids.contains(id));
        pending
            .iter()
            .filter(|a| !self.known.contains(&a.request_id))
            .copied()
            .collect()
    }

    fn mark_notified(&mut self, request_id: &str) {
        self.known.insert(request_id.to_owned());
    }
}

fn now_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

/// An atomic claim coordinates notifications across independent desktop clients.
fn claim(directory: &Path, request_id: &str) -> std::io::Result<bool> {
    fs::create_dir_all(directory)?;
    let name = format!("{:x}.claim", Sha256::digest(request_id.as_bytes()));
    match OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(directory.join(name))
    {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == ErrorKind::AlreadyExists => Ok(false),
        Err(error) => Err(error),
    }
}

fn release_claim(directory: &Path, request_id: &str) -> std::io::Result<()> {
    let name = format!("{:x}.claim", Sha256::digest(request_id.as_bytes()));
    match fs::remove_file(directory.join(name)) {
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(()),
        result => result,
    }
}

fn remove_old_claims(directory: &Path) {
    let Ok(entries) = fs::read_dir(directory) else {
        return;
    };
    for entry in entries.flatten() {
        if entry
            .path()
            .extension()
            .is_some_and(|extension| extension == "claim")
            && entry
                .metadata()
                .and_then(|m| m.modified())
                .ok()
                .is_some_and(|modified| {
                    modified.elapsed().unwrap_or_default() > Duration::from_secs(86400)
                })
        {
            let _ = fs::remove_file(entry.path());
        }
    }
}

fn is_current(app: &tauri::AppHandle, generation: u64) -> bool {
    app.state::<NotificationState>()
        .polling
        .lock()
        .expect("notification state poisoned")
        .generation
        == generation
}

fn is_background(app: &tauri::AppHandle) -> bool {
    app.get_webview_window("main").is_some_and(|window| {
        !window.is_visible().unwrap_or(false) || !window.is_focused().unwrap_or(false)
    })
}

#[tauri::command]
pub(crate) fn configure_approval_notifications(
    state: tauri::State<'_, NotificationState>,
    enabled: bool,
    title: String,
    body: String,
) {
    *state
        .preferences
        .lock()
        .expect("notification preferences poisoned") = Preferences {
        enabled,
        title,
        body,
    };
}

#[tauri::command]
pub(crate) async fn send_test_notification(
    app: tauri::AppHandle,
    title: String,
    body: String,
) -> Result<(), String> {
    let identifier = format!("qwenpaw-test:{}", uuid::Uuid::new_v4());
    notification_delivery::send(
        &app,
        &identifier,
        &title,
        &body,
        Duration::from_secs(15),
        None,
    )
    .await
}

#[tauri::command]
pub(crate) async fn get_notification_permission(
) -> Result<notification_delivery::Permission, String> {
    notification_delivery::permission().await
}

#[tauri::command]
pub(crate) async fn request_notification_permission(
) -> Result<notification_delivery::Permission, String> {
    notification_delivery::request_permission().await
}

#[tauri::command]
pub(crate) fn start_console_polling(
    app: tauri::AppHandle,
    token: String,
    agent_id: Option<String>,
    client_id: String,
    client_epoch: u64,
    request_seq: u64,
) -> Result<u64, String> {
    let directory = app
        .path()
        .app_cache_dir()
        .map_err(|e| e.to_string())?
        .join("approval-notifications");
    let client = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(10))
        .build()
        .map_err(|e| e.to_string())?;
    let state = app.state::<NotificationState>();
    let mut polling = state.polling.lock().expect("notification state poisoned");
    if !polling.claim_start(&client_id, client_epoch, request_seq) {
        return Err("This console polling request was superseded.".into());
    }
    if let Some(task) = polling.task.take() {
        task.abort();
    }
    polling.generation += 1;
    let generation = polling.generation;
    let handle = app.clone();
    polling.task = Some(tauri::async_runtime::spawn(async move {
        poll_console(handle, client, token, agent_id, directory, generation).await;
    }));
    Ok(generation)
}

#[tauri::command]
pub(crate) fn stop_console_polling(state: tauri::State<'_, NotificationState>, generation: u64) {
    let mut polling = state.polling.lock().expect("notification state poisoned");
    if polling.generation != generation {
        return;
    }
    polling.generation += 1;
    if let Some(task) = polling.task.take() {
        task.abort();
    }
}

async fn poll_console(
    app: tauri::AppHandle,
    client: reqwest::Client,
    token: String,
    agent_id: Option<String>,
    directory: PathBuf,
    generation: u64,
) {
    let cleanup_directory = directory.clone();
    let _ =
        tauri::async_runtime::spawn_blocking(move || remove_old_claims(&cleanup_directory)).await;
    let mut tracker = ApprovalTracker::default();
    let mut displayed = HashSet::new();
    while is_current(&app, generation) && !crate::tray::is_quitting(&app) {
        let enabled = app
            .state::<NotificationState>()
            .preferences
            .lock()
            .expect("notification preferences poisoned")
            .enabled;
        if !enabled {
            for id in displayed.drain() {
                notification_delivery::close(&format!("qwenpaw-approval:{id}")).await;
            }
        }
        if let Some(port) = crate::backend::console_port(&app) {
            let mut request =
                client.get(format!("http://127.0.0.1:{port}/api/console/push-messages"));
            if !token.is_empty() {
                request = request.bearer_auth(&token);
            }
            if let Some(agent) = &agent_id {
                request = request.header("X-Agent-Id", agent);
            }
            if let Ok(response) = request.send().await {
                if let Ok(response) = response.error_for_status() {
                    if let Ok(snapshot) = response.json::<Snapshot>().await {
                        if !is_current(&app, generation) {
                            return;
                        }
                        let fresh = tracker.fresh(&snapshot.pending_approvals, now_seconds());
                        let resolved: Vec<_> =
                            displayed.difference(&tracker.known).cloned().collect();
                        for id in resolved {
                            notification_delivery::close(&format!("qwenpaw-approval:{id}")).await;
                            displayed.remove(&id);
                        }
                        let _ = app.emit(
                            PUSH_EVENT,
                            PushEvent {
                                generation,
                                snapshot: &snapshot,
                            },
                        );
                        for approval in fresh {
                            let preferences = app
                                .state::<NotificationState>()
                                .preferences
                                .lock()
                                .expect("notification preferences poisoned")
                                .clone();
                            if !preferences.enabled || !is_background(&app) {
                                continue;
                            }
                            let claim_directory = directory.clone();
                            let id = approval.request_id.clone();
                            let claimed = tauri::async_runtime::spawn_blocking(move || {
                                claim(&claim_directory, &id)
                            })
                            .await;
                            if !matches!(claimed, Ok(Ok(true))) {
                                continue;
                            }
                            if !is_current(&app, generation)
                                || approval.expires_at() <= now_seconds()
                                || !app
                                    .state::<NotificationState>()
                                    .preferences
                                    .lock()
                                    .expect("notification preferences poisoned")
                                    .enabled
                            {
                                let directory = directory.clone();
                                let id = approval.request_id.clone();
                                let _ = tauri::async_runtime::spawn_blocking(move || {
                                    release_claim(&directory, &id)
                                })
                                .await;
                                continue;
                            }
                            let tool = approval
                                .tool_display_name
                                .as_deref()
                                .unwrap_or(&approval.tool_name);
                            let identifier = format!("qwenpaw-approval:{}", approval.request_id);
                            let lifetime = Duration::from_secs_f64(
                                (approval.expires_at() - now_seconds()).max(0.01),
                            );
                            if let Err(error) = notification_delivery::send(
                                &app,
                                &identifier,
                                &preferences.title,
                                &preferences.body.replace("{tool}", tool),
                                lifetime,
                                Some(approval.notification_target()),
                            )
                            .await
                            {
                                log::warn!("Could not deliver approval notification: {error}");
                                let directory = directory.clone();
                                let id = approval.request_id.clone();
                                let _ = tauri::async_runtime::spawn_blocking(move || {
                                    release_claim(&directory, &id)
                                })
                                .await;
                            } else {
                                tracker.mark_notified(&approval.request_id);
                                displayed.insert(approval.request_id.clone());
                            }
                        }
                    }
                }
            }
        }
        tokio::time::sleep(POLL_INTERVAL).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn approval(id: &str, created_at: f64) -> Approval {
        Approval {
            request_id: id.into(),
            root_session_id: None,
            agent_id: None,
            owner_agent_id: None,
            tool_name: "pwd".into(),
            tool_display_name: None,
            created_at,
            timeout_seconds: 300.0,
            rest: Map::new(),
        }
    }

    #[test]
    fn initial_snapshot_is_seeded_and_only_new_live_approvals_notify() {
        let mut tracker = ApprovalTracker::default();
        assert!(tracker
            .fresh(&[approval("existing", 100.0)], 110.0)
            .is_empty());
        let snapshot = [
            approval("existing", 100.0),
            approval("new", 120.0),
            approval("expired", 0.0),
        ];
        let fresh = tracker.fresh(&snapshot, 310.0);
        assert_eq!(fresh.len(), 1);
        assert_eq!(fresh[0].request_id, "new");
        assert_eq!(tracker.fresh(&snapshot, 311.0).len(), 1);
        tracker.mark_notified("new");
        assert!(tracker.fresh(&snapshot, 312.0).is_empty());
    }

    #[test]
    fn an_empty_initial_snapshot_allows_the_next_approval() {
        let mut tracker = ApprovalTracker::default();
        assert!(tracker.fresh(&[], 100.0).is_empty());
        assert_eq!(tracker.fresh(&[approval("new", 101.0)], 102.0).len(), 1);
    }

    #[test]
    fn foreground_approval_stays_pending_until_delivery_succeeds() {
        let mut tracker = ApprovalTracker::default();
        assert!(tracker.fresh(&[], 100.0).is_empty());
        let pending = [approval("new", 101.0)];
        assert_eq!(tracker.fresh(&pending, 102.0).len(), 1);
        assert_eq!(tracker.fresh(&pending, 103.0).len(), 1);
        tracker.mark_notified("new");
        assert!(tracker.fresh(&pending, 104.0).is_empty());
    }

    #[test]
    fn concurrent_desktop_clients_claim_an_approval_only_once() {
        let directory =
            std::env::temp_dir().join(format!("qwenpaw-notifications-{}", uuid::Uuid::new_v4()));
        let threads: Vec<_> = (0..8)
            .map(|_| {
                let directory = directory.clone();
                std::thread::spawn(move || claim(&directory, "same-request").unwrap())
            })
            .collect();
        let winners = threads
            .into_iter()
            .map(|thread| thread.join().unwrap())
            .filter(|won| *won)
            .count();
        assert_eq!(winners, 1);
        assert!(claim(&directory, "another-request").unwrap());
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn snapshot_preserves_approval_fields_for_the_frontend() {
        let value = serde_json::json!({"messages": [], "pending_approvals": [{
            "request_id": "r1", "tool_name": "Bash", "created_at": 100.0,
            "timeout_seconds": 300.0, "root_session_id": "session", "tool_params": {"command": "pwd"}
        }]});
        let snapshot: Snapshot = serde_json::from_value(value).unwrap();
        let serialized = serde_json::to_value(snapshot).unwrap();
        assert_eq!(
            serialized["pending_approvals"][0]["root_session_id"],
            "session"
        );
        assert_eq!(
            serialized["pending_approvals"][0]["tool_params"]["command"],
            "pwd"
        );
    }

    #[test]
    fn notification_target_uses_the_conversation_owner_agent() {
        let approval: Approval = serde_json::from_value(serde_json::json!({
            "request_id": "r1",
            "root_session_id": "session",
            "owner_agent_id": "owner",
            "agent_id": "executor",
            "tool_name": "Bash",
            "created_at": 100.0,
            "timeout_seconds": 300.0
        }))
        .unwrap();

        let target = approval.notification_target();
        assert_eq!(target.root_session_id.as_deref(), Some("session"));
        assert_eq!(target.agent_id.as_deref(), Some("owner"));
    }

    #[test]
    fn rejected_delivery_releases_the_claim_for_a_later_attempt() {
        let directory = std::env::temp_dir().join(format!(
            "qwenpaw-notification-retry-{}",
            uuid::Uuid::new_v4()
        ));
        assert!(claim(&directory, "request").unwrap());
        assert!(!claim(&directory, "request").unwrap());
        release_claim(&directory, "request").unwrap();
        assert!(claim(&directory, "request").unwrap());
        release_claim(&directory, "request").unwrap();
        release_claim(&directory, "request").unwrap();
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn stale_starts_from_the_same_console_are_rejected() {
        let mut polling = Polling::default();
        assert!(polling.claim_start("client-a", 100, 1));
        assert!(polling.claim_start("client-a", 100, 2));
        assert!(!polling.claim_start("client-a", 100, 1));
        assert!(!polling.claim_start("client-old", 99, 1));
        assert!(polling.claim_start("client-b", 101, 1));
    }
}
