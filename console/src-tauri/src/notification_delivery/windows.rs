//! Desktop Toast identity, COM activation, and history use the same AUMID.

use std::{
    ffi::OsString,
    sync::OnceLock,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use tauri::Manager;
use windows::{
    core::{implement, IUnknown, Interface, Ref, BOOL, GUID, HSTRING, PCWSTR},
    Data::Xml::Dom::XmlDocument,
    Foundation::{DateTime, IReference, PropertyValue},
    Win32::{
        Foundation::{CLASS_E_NOAGGREGATION, E_INVALIDARG, E_POINTER},
        System::Com::{
            CoRegisterClassObject, CoRevokeClassObject, IClassFactory, IClassFactory_Impl,
            CLSCTX_LOCAL_SERVER, REGCLS_MULTIPLEUSE,
        },
        UI::{
            Notifications::{
                INotificationActivationCallback, INotificationActivationCallback_Impl,
                NOTIFICATION_USER_INPUT_DATA,
            },
            Shell::SetCurrentProcessExplicitAppUserModelID,
        },
    },
    UI::Notifications::{ToastNotification, ToastNotificationManager, ToastNotifier},
};
use winreg::{enums::HKEY_CURRENT_USER, RegKey};

use super::{open_target, toast_xml, windows_tag, HashMap, Mutex, WindowsActivation};

const ACTIVATOR_CLSID: GUID = GUID::from_u128(0x62caebf9_1414_4c33_a459_ba348f27fecc);
const GROUP: &str = "qwenpaw";

struct Registration(u32);

impl Drop for Registration {
    fn drop(&mut self) {
        unsafe {
            let _ = CoRevokeClassObject(self.0);
        }
    }
}

#[implement(INotificationActivationCallback)]
struct Activator(tauri::AppHandle);

impl INotificationActivationCallback_Impl for Activator_Impl {
    fn Activate(
        &self,
        _app_id: &PCWSTR,
        args: &PCWSTR,
        _data: *const NOTIFICATION_USER_INPUT_DATA,
        _count: u32,
    ) -> windows::core::Result<()> {
        let args = unsafe { args.to_string() }?;
        let activation: WindowsActivation = serde_json::from_str(&args)
            .map_err(|error| windows::core::Error::new(E_INVALIDARG, error.to_string()))?;
        // Restore first; history cleanup must never block activation.
        open_target(&self.0, activation.target.as_ref());
        tauri::async_runtime::spawn(async move {
            close(&activation.identifier).await;
        });
        Ok(())
    }
}

#[implement(IClassFactory)]
struct Factory(tauri::AppHandle);

impl IClassFactory_Impl for Factory_Impl {
    fn CreateInstance(
        &self,
        outer: Ref<'_, IUnknown>,
        iid: *const GUID,
        object: *mut *mut std::ffi::c_void,
    ) -> windows::core::Result<()> {
        if iid.is_null() || object.is_null() {
            return Err(E_POINTER.into());
        }
        unsafe {
            *object = std::ptr::null_mut();
        }
        if outer.is_some() {
            return Err(CLASS_E_NOAGGREGATION.into());
        }
        let activator: INotificationActivationCallback = Activator(self.0.clone()).into();
        unsafe { activator.query(iid, object).ok() }
    }

    fn LockServer(&self, _lock: BOOL) -> windows::core::Result<()> {
        Ok(())
    }
}

pub(crate) fn setup(app: &tauri::AppHandle) -> Result<(), String> {
    let app_id = &app.config().identifier;
    let name = app
        .config()
        .product_name
        .as_deref()
        .unwrap_or("QwenPaw Desktop");
    let executable = std::env::current_exe().map_err(|error| error.to_string())?;
    let clsid = format!("{{{ACTIVATOR_CLSID:?}}}");
    let root = RegKey::predef(HKEY_CURRENT_USER);
    let register = || -> Result<(), Box<dyn std::error::Error>> {
        let (identity, _) =
            root.create_subkey(format!(r"Software\Classes\AppUserModelId\{app_id}"))?;
        identity.set_value("DisplayName", &name)?;
        identity.set_value("CustomActivator", &clsid)?;
        let (server, _) =
            root.create_subkey(format!(r"Software\Classes\CLSID\{clsid}\LocalServer32"))?;
        let mut command = OsString::from("\"");
        command.push(&executable);
        command.push("\" --toast-activated");
        server.set_value("", &command)?;
        server.set_value("ServerExecutable", &executable.as_os_str())?;
        unsafe {
            SetCurrentProcessExplicitAppUserModelID(&HSTRING::from(app_id))?;
        }
        let factory: IClassFactory = Factory(app.clone()).into();
        // Wry has initialized COM on this main thread and pumps its messages.
        let cookie = unsafe {
            CoRegisterClassObject(
                &ACTIVATOR_CLSID,
                &factory,
                CLSCTX_LOCAL_SERVER,
                REGCLS_MULTIPLEUSE,
            )?
        };
        app.manage(Registration(cookie));
        Ok(())
    };
    register().map_err(|error| error.to_string())
}

#[derive(Clone)]
struct ActiveNotification {
    toast: ToastNotification,
    notifier: ToastNotifier,
    app_id: HSTRING,
}

fn active() -> &'static Mutex<HashMap<String, ActiveNotification>> {
    static ACTIVE: OnceLock<Mutex<HashMap<String, ActiveNotification>>> = OnceLock::new();
    ACTIVE.get_or_init(|| Mutex::new(HashMap::new()))
}

pub(super) fn show(
    app_id: &str,
    identifier: &str,
    title: &str,
    body: &str,
    lifetime: Duration,
    target: Option<super::NotificationTarget>,
) -> Result<(), String> {
    let send = || -> Result<(), Box<dyn std::error::Error>> {
        let launch = serde_json::to_string(&WindowsActivation {
            identifier: identifier.to_owned(),
            target,
        })?;
        let document = XmlDocument::new()?;
        document.LoadXml(&HSTRING::from(toast_xml(title, body, &launch)))?;
        let toast = ToastNotification::CreateToastNotification(&document)?;
        toast.SetTag(&HSTRING::from(windows_tag(identifier)))?;
        toast.SetGroup(&HSTRING::from(GROUP))?;
        let expiry = SystemTime::now().duration_since(UNIX_EPOCH)? + lifetime;
        let date = DateTime {
            UniversalTime: (expiry.as_nanos() / 100) as i64 + 116_444_736_000_000_000,
        };
        toast.SetExpirationTime(
            &PropertyValue::CreateDateTime(date)?.cast::<IReference<DateTime>>()?,
        )?;
        let app_id = HSTRING::from(app_id);
        let notifier = ToastNotificationManager::CreateToastNotifierWithId(&app_id)?;
        notifier.Show(&toast)?;
        active()
            .lock()
            .expect("Windows notifications poisoned")
            .insert(
                identifier.to_owned(),
                ActiveNotification {
                    toast,
                    notifier,
                    app_id,
                },
            );
        Ok(())
    };
    send().map_err(|error| error.to_string())
}

pub(super) async fn close(identifier: &str) {
    let notification = active()
        .lock()
        .expect("Windows notifications poisoned")
        .remove(identifier);
    let Some(notification) = notification else {
        return;
    };
    let tag = windows_tag(identifier);
    for attempt in 0..3 {
        let active = notification.clone();
        let cleanup_tag = tag.clone();
        let result = tauri::async_runtime::spawn_blocking(move || {
            let _ = active.notifier.Hide(&active.toast);
            ToastNotificationManager::History()
                .and_then(|history| {
                    let notifications = history.GetHistoryWithId(&active.app_id)?;
                    let present = notifications.into_iter().any(|toast| {
                        toast.Tag().ok().is_some_and(|value| value == cleanup_tag)
                            && toast.Group().ok().is_some_and(|value| value == GROUP)
                    });
                    if !present {
                        return Ok(());
                    }
                    history.RemoveGroupedTagWithId(
                        &HSTRING::from(cleanup_tag),
                        &HSTRING::from(GROUP),
                        &active.app_id,
                    )
                })
                .map_err(|error| error.to_string())
        })
        .await;
        match result {
            Ok(Ok(())) => return,
            result if attempt == 2 => log::warn!(
                "Could not remove Windows notification: app_id={} tag={tag} group={GROUP}: {result:?}",
                notification.app_id,
            ),
            _ => tokio::time::sleep(Duration::from_millis(100)).await,
        }
    }
}
