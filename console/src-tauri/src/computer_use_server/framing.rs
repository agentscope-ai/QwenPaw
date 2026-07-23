//! Length-prefixed JSON framing over the Computer Use pipe connection.

use serde_json::{json, Value};
use std::fs::File;
use std::io::{Read, Write};

use super::MAX_FRAME_BYTES;

pub(super) fn request_id(message: &Value) -> Result<String, String> {
    message
        .get("request_id")
        .and_then(Value::as_str)
        .map(str::to_string)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "request_id is required".to_string())
}

pub(super) fn read_message(connection: &mut File) -> Result<Value, String> {
    let mut header = [0_u8; 4];
    connection
        .read_exact(&mut header)
        .map_err(|error| error.to_string())?;
    let length = u32::from_le_bytes(header) as usize;
    if length == 0 || length > MAX_FRAME_BYTES {
        return Err("Invalid Computer Use frame length".to_string());
    }
    let mut payload = vec![0_u8; length];
    connection
        .read_exact(&mut payload)
        .map_err(|error| error.to_string())?;
    serde_json::from_slice(&payload).map_err(|error| error.to_string())
}

pub(super) fn write_result(
    connection: &mut File,
    request_id: &str,
    result: Value,
) -> Result<(), String> {
    write_message(
        connection,
        &json!({"request_id": request_id, "ok": true, "result": result}),
    )
}

pub(super) fn write_error(
    connection: &mut File,
    request_id: &str,
    code: &str,
    message: &str,
) -> Result<(), String> {
    write_message(
        connection,
        &json!({"request_id": request_id, "ok": false, "error": {"code": code, "message": message}}),
    )
}

pub(super) fn write_message(connection: &mut File, message: &Value) -> Result<(), String> {
    let payload = serde_json::to_vec(message).map_err(|error| error.to_string())?;
    let length = u32::try_from(payload.len()).map_err(|_| "Frame is too large".to_string())?;
    connection
        .write_all(&length.to_le_bytes())
        .map_err(|error| error.to_string())?;
    connection
        .write_all(&payload)
        .map_err(|error| error.to_string())?;
    connection.flush().map_err(|error| error.to_string())
}

pub(super) fn wide_string(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(Some(0)).collect()
}
