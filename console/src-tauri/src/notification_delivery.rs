//! Platform notification authorization and delivery acknowledgement.

use std::time::Duration;

use serde::Serialize;
#[cfg(target_os = "macos")]
use tauri::Emitter;
#[cfg(not(target_os = "macos"))]
use tauri_plugin_notification::NotificationExt;

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ApprovalNotificationTarget {
    pub(crate) request_id: String,
    pub(crate) root_session_id: Option<String>,
    pub(crate) agent_id: Option<String>,
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
    #[cfg(not(target_os = "macos"))]
    let _ = identifier;
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
                let target_app = app.clone();
                let _ = app.run_on_main_thread(move || {
                    crate::tray::show_main_window(&target_app);
                    if let Some(target) = click_target {
                        let _ = target_app.emit("qwenpaw:open-approval", target);
                    } else {
                        let _ = target_app.emit("qwenpaw:open-approvals", ());
                    }
                });
            }
        });
        Ok(())
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = (identifier, lifetime, click_target);
        app.notification()
            .builder()
            .title(title)
            .body(body)
            .show()
            .map_err(|error| error.to_string())
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
