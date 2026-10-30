//! Platform notification authorization and delivery acknowledgement.

use std::time::Duration;

use serde::Serialize;
use tauri::Emitter;
#[cfg(target_os = "windows")]
use tauri::Manager;

#[cfg(all(unix, not(target_os = "macos")))]
use {
    notify_rust::{Notification, NotificationHandle, NotificationResponse, Timeout},
    std::{
        collections::HashMap,
        sync::{Arc, Mutex, OnceLock},
    },
};

#[cfg(target_os = "windows")]
use windows::{
    core::HSTRING,
    Data::Xml::Dom::XmlDocument,
    Foundation::TypedEventHandler,
    UI::Notifications::{ToastNotification, ToastNotificationManager, ToastNotifier},
};

#[cfg(target_os = "windows")]
use std::{
    collections::HashMap,
    sync::{Mutex, OnceLock},
};

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ApprovalNotificationTarget {
    pub(crate) request_id: String,
    pub(crate) root_session_id: Option<String>,
    pub(crate) agent_id: Option<String>,
}

#[cfg(target_os = "windows")]
const WINDOWS_POWERSHELL_APP_ID: &str = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\
     \\WindowsPowerShell\\v1.0\\powershell.exe";

#[cfg(target_os = "windows")]
struct WindowsNotification {
    notification: ToastNotification,
    notifier: ToastNotifier,
    app_id: HSTRING,
    activated_token: Option<i64>,
}

#[cfg(target_os = "windows")]
impl WindowsNotification {
    fn unregister(&mut self) {
        if let Some(token) = self.activated_token.take() {
            let _ = self.notification.RemoveActivated(token);
        }
    }
}

#[cfg(target_os = "windows")]
impl Drop for WindowsNotification {
    fn drop(&mut self) {
        self.unregister();
    }
}

#[cfg(target_os = "windows")]
fn active_windows_notifications() -> &'static Mutex<HashMap<String, WindowsNotification>> {
    static ACTIVE: OnceLock<Mutex<HashMap<String, WindowsNotification>>> = OnceLock::new();
    ACTIVE.get_or_init(|| Mutex::new(HashMap::new()))
}

fn open_target(app: &tauri::AppHandle, target: Option<&ApprovalNotificationTarget>) {
    let app = app.clone();
    let target = target.cloned();
    let main_app = app.clone();
    let _ = app.run_on_main_thread(move || {
        crate::tray::show_main_window(&main_app);
        if let Some(target) = target {
            let _ = main_app.emit("qwenpaw:open-approval", target);
        } else {
            let _ = main_app.emit("qwenpaw:open-approvals", ());
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
    click_target: Option<ApprovalNotificationTarget>,
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
fn toast_xml(title: &str, body: &str) -> String {
    format!(
        "<toast><visual><binding template=\"ToastGeneric\">\
         <text>{}</text><text>{}</text></binding></visual></toast>",
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

#[cfg(target_os = "windows")]
fn close_windows(identifier: &str) {
    let active = active_windows_notifications()
        .lock()
        .expect("Windows notifications poisoned")
        .remove(identifier);
    if let Some(mut active) = active {
        active.unregister();
        let _ = active.notifier.Hide(&active.notification);
        let removed = ToastNotificationManager::History().and_then(|history| {
            history.RemoveGroupedTagWithId(
                &HSTRING::from(windows_tag(identifier)),
                &HSTRING::new(),
                &active.app_id,
            )
        });
        if let Err(error) = removed {
            log::warn!("Could not remove Windows notification: {error}");
        }
    }
}

#[cfg(target_os = "windows")]
fn show_windows(
    app: &tauri::AppHandle,
    identifier: &str,
    title: &str,
    body: &str,
    click_target: Option<ApprovalNotificationTarget>,
) -> Result<(), String> {
    let document = XmlDocument::new().map_err(|error| error.to_string())?;
    document
        .LoadXml(&HSTRING::from(toast_xml(title, body)))
        .map_err(|error| error.to_string())?;
    let notification =
        ToastNotification::CreateToastNotification(&document).map_err(|error| error.to_string())?;
    notification
        .SetTag(&HSTRING::from(windows_tag(identifier)))
        .map_err(|error| error.to_string())?;

    let activated_app = app.clone();
    let activated_target = click_target;
    let activated_identifier = identifier.to_owned();
    let activated = TypedEventHandler::new(move |_, _args| {
        close_windows(&activated_identifier);
        open_target(&activated_app, activated_target.as_ref());
        Ok(())
    });
    let activated_token = notification
        .Activated(&activated)
        .map_err(|error| error.to_string())?;

    let app_id = if tauri::is_dev() {
        WINDOWS_POWERSHELL_APP_ID.to_owned()
    } else {
        app.config().identifier.clone()
    };
    let app_id = HSTRING::from(app_id);
    let notifier = ToastNotificationManager::CreateToastNotifierWithId(&app_id)
        .map_err(|error| error.to_string())?;
    // WinRT must keep the toast and its handler alive after Show returns.
    let previous = active_windows_notifications()
        .lock()
        .expect("Windows notifications poisoned")
        .insert(
            identifier.to_owned(),
            WindowsNotification {
                notification: notification.clone(),
                notifier: notifier.clone(),
                app_id,
                activated_token: Some(activated_token),
            },
        );
    drop(previous);
    if let Err(error) = notifier.Show(&notification) {
        close_windows(identifier);
        return Err(error.to_string());
    }
    Ok(())
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
    close_windows(identifier);
    #[cfg(all(unix, not(target_os = "macos")))]
    close_linux(identifier).await;
}

pub(crate) async fn send(
    app: &tauri::AppHandle,
    identifier: &str,
    title: &str,
    body: &str,
    lifetime: Duration,
    click_target: Option<ApprovalNotificationTarget>,
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
        show_windows(app, identifier, title, body, click_target)?;
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
    use super::{toast_xml, windows_tag, ApprovalNotificationTarget};

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
        let xml = toast_xml("Qwen & Paw", "<approval>");
        assert!(xml.contains("Qwen &amp; Paw"));
        assert!(xml.contains("&lt;approval&gt;"));
    }

    #[test]
    fn windows_toast_tags_are_stable_and_short() {
        let first = windows_tag("qwenpaw-approval:request-1");
        assert_eq!(first, windows_tag("qwenpaw-approval:request-1"));
        assert_eq!(first.len(), 16);
        assert_ne!(first, windows_tag("qwenpaw-approval:request-2"));
    }
}
