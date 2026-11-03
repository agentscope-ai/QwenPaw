//! Platform notification authorization and delivery acknowledgement.

use std::{collections::HashMap, sync::Mutex, time::Duration};

use serde::{Deserialize, Serialize};
use tauri::{Emitter, Manager};

#[cfg(target_os = "windows")]
#[path = "notification_delivery/windows.rs"]
mod windows;
#[cfg(target_os = "windows")]
pub(crate) use windows::setup;

#[cfg(all(unix, not(target_os = "macos")))]
use {
    notify_rust::{Notification, NotificationHandle, NotificationResponse, Timeout},
    std::sync::{Arc, OnceLock},
};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ApprovalNotificationTarget {
    pub(crate) request_id: String,
    pub(crate) root_session_id: Option<String>,
    pub(crate) agent_id: Option<String>,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(tag = "kind", content = "target", rename_all = "lowercase")]
pub(crate) enum NotificationTarget {
    Approval(ApprovalNotificationTarget),
    Event(crate::notifications::NotificationEvent),
}

#[derive(Default)]
pub(crate) struct ActivationState(Mutex<HashMap<String, NotificationTarget>>);

impl ActivationState {
    fn record(&self, target: NotificationTarget) {
        self.0
            .lock()
            .expect("notification activation poisoned")
            .insert(target.kind().to_owned(), target);
    }

    fn take(&self, kind: &str) -> Option<NotificationTarget> {
        self.0
            .lock()
            .expect("notification activation poisoned")
            .remove(kind)
    }
}

impl NotificationTarget {
    fn kind(&self) -> &'static str {
        match self {
            Self::Approval(_) => "approval",
            Self::Event(_) => "event",
        }
    }
}

// A COM activation can arrive before the console has mounted its listeners.
#[tauri::command]
pub(crate) fn take_notification_target(
    state: tauri::State<'_, ActivationState>,
    kind: String,
) -> Option<NotificationTarget> {
    state.take(&kind)
}

#[cfg(any(target_os = "windows", test))]
#[derive(Deserialize, Serialize)]
struct WindowsActivation {
    identifier: String,
    target: Option<NotificationTarget>,
}

fn open_target(app: &tauri::AppHandle, target: Option<&NotificationTarget>) {
    let app = app.clone();
    let target = target.cloned();
    let main_app = app.clone();
    let _ = app.run_on_main_thread(move || {
        crate::tray::show_main_window(&main_app);
        if let Some(target) = &target {
            main_app.state::<ActivationState>().record(target.clone());
        }
        match target {
            Some(NotificationTarget::Approval(target)) => {
                let _ = main_app.emit("qwenpaw:open-approval", target);
            }
            Some(NotificationTarget::Event(event)) => {
                let _ = main_app.emit("qwenpaw:open-notification", event);
            }
            None => {
                let _ = main_app.emit("qwenpaw:open-approvals", ());
            }
        }
    });
}

#[cfg(all(unix, not(target_os = "macos")))]
fn active_linux_notifications() -> &'static Mutex<HashMap<String, Arc<NotificationHandle>>> {
    static ACTIVE: OnceLock<Mutex<HashMap<String, Arc<NotificationHandle>>>> = OnceLock::new();
    ACTIVE.get_or_init(|| Mutex::new(HashMap::new()))
}

#[cfg(all(unix, not(target_os = "macos")))]
async fn show_linux(
    app: tauri::AppHandle,
    identifier: &str,
    title: &str,
    body: &str,
    lifetime: Duration,
    click_target: Option<NotificationTarget>,
) -> Result<(), String> {
    let timeout_ms = lifetime.as_millis().min(i32::MAX as u128) as u32;
    let title = title.to_owned();
    let body = body.to_owned();
    let handle = tauri::async_runtime::spawn_blocking(move || {
        Notification::new()
            .appname("QwenPaw")
            .summary(&title)
            .body(&body)
            .action("default", &title)
            .timeout(Timeout::Milliseconds(timeout_ms))
            .show()
    })
    .await
    .map_err(|error| error.to_string())?
    .map_err(|error| error.to_string())?;
    let handle = Arc::new(handle);
    active_linux_notifications()
        .lock()
        .expect("Linux notifications poisoned")
        .insert(identifier.to_owned(), handle.clone());

    let identifier = identifier.to_owned();
    tauri::async_runtime::spawn(async move {
        let callback_app = app;
        let callback_target = click_target;
        handle
            .wait_for_action_async(move |response| {
                if matches!(
                    response,
                    NotificationResponse::Default | NotificationResponse::Action(_)
                ) {
                    open_target(&callback_app, callback_target.as_ref());
                }
            })
            .await;
        active_linux_notifications()
            .lock()
            .expect("Linux notifications poisoned")
            .remove(&identifier);
    });
    Ok(())
}

#[cfg(all(unix, not(target_os = "macos")))]
async fn close_linux(identifier: &str) {
    let handle = active_linux_notifications()
        .lock()
        .expect("Linux notifications poisoned")
        .remove(identifier);
    if let Some(handle) = handle {
        handle.close_async().await;
    }
}

#[cfg(any(target_os = "windows", test))]
fn xml(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

#[cfg(any(target_os = "windows", test))]
fn toast_xml(title: &str, body: &str, launch: &str) -> String {
    format!(
        "<toast launch=\"{}\"><visual><binding template=\"ToastGeneric\">\
         <text>{}</text><text>{}</text></binding></visual></toast>",
        xml(launch),
        xml(title),
        xml(body)
    )
}

#[cfg(any(target_os = "windows", test))]
fn windows_tag(identifier: &str) -> String {
    use sha2::{Digest, Sha256};

    let digest = format!("{:x}", Sha256::digest(identifier.as_bytes()));
    digest[..16].to_owned()
}

#[cfg(not(target_os = "macos"))]
fn schedule_expiry(identifier: &str, lifetime: Duration) {
    let identifier = identifier.to_owned();
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(lifetime).await;
        close(&identifier).await;
    });
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize)]
#[serde(rename_all = "lowercase")]
pub(crate) enum Permission {
    #[cfg(target_os = "macos")]
    Default,
    #[cfg(target_os = "macos")]
    Granted,
    #[cfg(target_os = "macos")]
    Denied,
    #[cfg(not(target_os = "macos"))]
    #[serde(rename = "native")]
    Managed,
}

#[cfg(target_os = "macos")]
fn permission_from_status(status: mac_usernotifications::AuthorizationStatus) -> Permission {
    use mac_usernotifications::AuthorizationStatus as Status;
    match status {
        Status::NotDetermined => Permission::Default,
        Status::Authorized | Status::Provisional | Status::Ephemeral => Permission::Granted,
        _ => Permission::Denied,
    }
}

pub(crate) async fn permission() -> Result<Permission, String> {
    #[cfg(target_os = "macos")]
    {
        let settings = mac_usernotifications::get_notification_settings()
            .await
            .map_err(|error| error.to_string())?;
        Ok(permission_from_status(settings.authorization_status))
    }
    #[cfg(not(target_os = "macos"))]
    Ok(Permission::Managed)
}

pub(crate) async fn request_permission() -> Result<Permission, String> {
    #[cfg(target_os = "macos")]
    {
        let granted = mac_usernotifications::request_auth()
            .await
            .map_err(|error| error.to_string())?;
        Ok(if granted {
            Permission::Granted
        } else {
            Permission::Denied
        })
    }
    #[cfg(not(target_os = "macos"))]
    Ok(Permission::Managed)
}

pub(crate) async fn close(identifier: &str) {
    #[cfg(target_os = "macos")]
    mac_usernotifications::close_delivered(identifier).await;
    #[cfg(target_os = "windows")]
    windows::close(identifier).await;
    #[cfg(all(unix, not(target_os = "macos")))]
    close_linux(identifier).await;
}

pub(crate) async fn send(
    app: &tauri::AppHandle,
    identifier: &str,
    title: &str,
    body: &str,
    lifetime: Duration,
    click_target: Option<NotificationTarget>,
) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        if permission().await? != Permission::Granted {
            return Err("Notification permission has not been granted for QwenPaw".into());
        }
        let handle = mac_usernotifications::Notification::new()
            .id(identifier)
            .title(title)
            .message(body)
            .default_sound()
            .timeout(lifetime)
            .send()
            .await
            .map_err(|error| error.to_string())?;
        let app = app.clone();
        let id = identifier.to_owned();
        tauri::async_runtime::spawn(async move {
            let response = handle.response().await;
            close(&id).await;
            if matches!(response, Ok(response) if response.is_default_action()) {
                open_target(&app, click_target.as_ref());
            }
        });
        Ok(())
    }
    #[cfg(target_os = "windows")]
    {
        let app_id = app.config().identifier.clone();
        let identifier_owned = identifier.to_owned();
        let title = title.to_owned();
        let body = body.to_owned();
        tauri::async_runtime::spawn_blocking(move || {
            windows::show(
                &app_id,
                &identifier_owned,
                &title,
                &body,
                lifetime,
                click_target,
            )
        })
        .await
        .map_err(|error| error.to_string())??;
        schedule_expiry(identifier, lifetime);
        Ok(())
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        show_linux(app.clone(), identifier, title, body, lifetime, click_target).await?;
        schedule_expiry(identifier, lifetime);
        Ok(())
    }
}

#[cfg(all(test, target_os = "macos"))]
mod tests {
    use super::*;
    use mac_usernotifications::AuthorizationStatus as Status;

    #[test]
    fn reports_permission_without_treating_missing_consent_as_granted() {
        assert_eq!(
            permission_from_status(Status::NotDetermined),
            Permission::Default
        );
        assert_eq!(permission_from_status(Status::Denied), Permission::Denied);
        assert_eq!(
            permission_from_status(Status::Authorized),
            Permission::Granted
        );
        assert_eq!(
            permission_from_status(Status::Provisional),
            Permission::Granted
        );
        assert_eq!(permission_from_status(Status::Unknown), Permission::Denied);
    }
}

#[cfg(test)]
mod cross_platform_tests {
    use super::{
        toast_xml, windows_tag, ActivationState, ApprovalNotificationTarget, NotificationTarget,
        WindowsActivation,
    };

    #[test]
    fn windows_activation_preserves_unicode_and_the_complete_click_target() {
        let activation = WindowsActivation {
            identifier: "qwenpaw-approval:request-1".into(),
            target: Some(NotificationTarget::Approval(ApprovalNotificationTarget {
                request_id: "审批<&\"1".into(),
                root_session_id: Some("会话 /?&1".into()),
                agent_id: Some("agent-2".into()),
            })),
        };
        let json = serde_json::to_string(&activation).unwrap();
        let decoded: WindowsActivation = serde_json::from_str(&json).unwrap();
        assert_eq!(decoded.identifier, activation.identifier);
        let Some(NotificationTarget::Approval(target)) = decoded.target else {
            panic!("approval activation lost its target");
        };
        assert_eq!(target.request_id, "审批<&\"1");
        assert_eq!(target.root_session_id.as_deref(), Some("会话 /?&1"));
        assert_eq!(target.agent_id.as_deref(), Some("agent-2"));
        assert!(toast_xml("Title", "Body", &json).contains("&quot;"));
    }

    #[test]
    fn activation_waits_for_its_listener_and_is_consumed_only_once() {
        let state = ActivationState::default();
        state.record(NotificationTarget::Approval(ApprovalNotificationTarget {
            request_id: "request-1".into(),
            root_session_id: None,
            agent_id: None,
        }));
        assert!(state.take("event").is_none());
        let Some(NotificationTarget::Approval(target)) = state.take("approval") else {
            panic!("startup activation was lost");
        };
        assert_eq!(target.request_id, "request-1");
        assert!(state.take("approval").is_none());
    }

    #[test]
    fn approval_click_target_matches_frontend_event_fields() {
        let target = ApprovalNotificationTarget {
            request_id: "approval-1".into(),
            root_session_id: Some("session-1".into()),
            agent_id: Some("agent-1".into()),
        };
        assert_eq!(
            serde_json::to_value(target).unwrap(),
            serde_json::json!({
                "requestId": "approval-1",
                "rootSessionId": "session-1",
                "agentId": "agent-1",
            })
        );
    }

    #[test]
    fn windows_toast_text_is_escaped() {
        let xml = toast_xml("Qwen & Paw", "<approval>", "a&b\"c");
        assert!(xml.contains("Qwen &amp; Paw"));
        assert!(xml.contains("&lt;approval&gt;"));
        assert!(xml.contains("launch=\"a&amp;b&quot;c\""));
    }

    #[test]
    fn windows_toast_tags_are_stable_and_short() {
        let first = windows_tag("qwenpaw-approval:request-1");
        assert_eq!(first, windows_tag("qwenpaw-approval:request-1"));
        assert_eq!(first.len(), 16);
        assert_ne!(first, windows_tag("qwenpaw-approval:request-2"));
    }
}
