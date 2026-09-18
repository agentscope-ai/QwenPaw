//! EventStream v1 request dispatcher and connection-owned lifecycle.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use serde_json::{Map, Value};

use super::event_stream_recorder::EventStreamRecorder;
use super::PROTOCOL_VERSION;

const MAX_OPERATION_CACHE: usize = 128;
const METHODS: &[&str] = &[
    "event_stream.cancel",
    "event_stream.pause",
    "event_stream.permission.request",
    "event_stream.release",
    "event_stream.resume",
    "event_stream.start",
    "event_stream.status",
    "event_stream.stop",
];
static NEXT_CONNECTION_ID: AtomicU64 = AtomicU64::new(1);

type NativeResult = Result<Value, (&'static str, String)>;

#[derive(Clone)]
struct CachedOperation {
    operation_id: String,
    method: String,
    params: Map<String, Value>,
    result: NativeResult,
}

pub(super) struct EventStreamConnection {
    id: u64,
    recorder: Arc<EventStreamRecorder>,
    operations: VecDeque<CachedOperation>,
}

impl EventStreamConnection {
    pub(super) fn new(recorder: Arc<EventStreamRecorder>) -> Self {
        Self {
            id: NEXT_CONNECTION_ID.fetch_add(1, Ordering::Relaxed),
            recorder,
            operations: VecDeque::new(),
        }
    }

    pub(super) fn dispatch(&mut self, message: &Value) -> NativeResult {
        if message.get("protocol_version").and_then(Value::as_u64) != Some(PROTOCOL_VERSION) {
            return Err((
                "protocol_mismatch",
                "Unsupported protocol version.".to_string(),
            ));
        }
        let method = message
            .get("method")
            .and_then(Value::as_str)
            .ok_or(("invalid_request", "Request method is missing.".to_string()))?;
        if !METHODS.contains(&method) {
            return Err((
                "unsupported_operation",
                format!("{method:?} is not an EventStream v1 method."),
            ));
        }
        let params = message
            .get("params")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        if method == "event_stream.status" {
            let id = if params.contains_key("recording_id") {
                Some(required_string(&params, "recording_id")?)
            } else {
                None
            };
            return Ok(self.recorder.recording_status(id));
        }
        let operation_id = required_string(&params, "operation_id")?;
        if let Some(cached) = self
            .operations
            .iter()
            .find(|cached| cached.operation_id == operation_id)
        {
            if cached.method != method || cached.params != params {
                return Err((
                    "idempotency_conflict",
                    "operation_id was already used with different parameters.".to_string(),
                ));
            }
            // A cached file reference must not outlive artifact retention or
            // an explicit release. Other acknowledgments remain immutable.
            return if method == "event_stream.stop" {
                self.recorder
                    .stop(self.id, required_string(&params, "recording_id")?)
            } else {
                cached.result.clone()
            };
        }

        let result = match method {
            "event_stream.start" => self
                .recorder
                .start(self.id, required_string(&params, "recording_id")?),
            "event_stream.pause" => self
                .recorder
                .pause(self.id, required_string(&params, "recording_id")?),
            "event_stream.resume" => self
                .recorder
                .resume(self.id, required_string(&params, "recording_id")?),
            "event_stream.stop" => self
                .recorder
                .stop(self.id, required_string(&params, "recording_id")?),
            "event_stream.cancel" => self
                .recorder
                .cancel(self.id, required_string(&params, "recording_id")?),
            "event_stream.release" => self
                .recorder
                .release(required_string(&params, "events_ref")?),
            "event_stream.permission.request" => self.recorder.request_permissions(),
            _ => unreachable!("method allowlist and dispatcher must stay aligned"),
        };
        // Cache only acknowledged state changes. A denied permission or busy
        // precondition must be retryable after the user or other owner clears
        // it; a successful response lost in transit must not execute twice.
        if result.is_ok() {
            self.operations.push_back(CachedOperation {
                operation_id: operation_id.to_string(),
                method: method.to_string(),
                params,
                result: result.clone(),
            });
            if self.operations.len() > MAX_OPERATION_CACHE {
                self.operations.pop_front();
            }
        }
        result
    }
}

impl Drop for EventStreamConnection {
    fn drop(&mut self) {
        self.recorder.disconnect(self.id);
    }
}

fn required_string<'a>(
    params: &'a Map<String, Value>,
    field: &str,
) -> Result<&'a str, (&'static str, String)> {
    params
        .get(field)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or(("invalid_request", format!("{field} is required.")))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn event_stream_method_set_is_narrow_and_versioned() {
        assert!(METHODS.contains(&"event_stream.start"));
        assert!(METHODS.contains(&"event_stream.release"));
        assert!(!METHODS.contains(&"click"));
        assert!(!METHODS.contains(&"rpc.call"));
    }

    #[test]
    fn required_fields_reject_empty_strings() {
        let params = Map::new();
        assert_eq!(
            required_string(&params, "operation_id").unwrap_err().0,
            "invalid_request"
        );
    }
}
